"""Phase 3: Concurrent inventory movement testing."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg2


DATABASE_URL = os.environ["DATABASE_URL"]
ROUNDS = 10
FIXTURE_NAME = "INVENTORY CONCURRENCY TEST FIXTURE"


def connect():
    return psycopg2.connect(DATABASE_URL)


def create_fixture():
    """Create a synthetic product with 10 units of stock."""

    with connect() as conn, conn.cursor() as cur:

        cur.execute("""
            SELECT GREATEST(
                COALESCE((SELECT MAX(product_id) FROM products), 0),
                COALESCE((SELECT MAX(product_id) FROM inventory_log), 0),
                COALESCE((SELECT MAX(product_id) FROM order_items), 0)
            ) + 1000
        """)

        product_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO products (
                product_id,
                product_name,
                price,
                stock_quantity,
                created_at
            )
            VALUES (%s, %s, 100.00, 10, CURRENT_TIMESTAMP)
        """, (product_id, FIXTURE_NAME))

    return product_id


def get_customer():
    """Retrieve an existing customer ID for checkout testing."""

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT MIN(customer_id) FROM customers")
        customer_id = cur.fetchone()[0]

    if customer_id is None:
        raise RuntimeError("No customer available for checkout testing.")

    return customer_id


def execute_operation(product_id, customer_id, operation, barrier):
    """Execute one operation through its own database connection."""

    conn = None

    try:
        conn = connect()
        conn.autocommit = True

        with conn.cursor() as cur:

            cur.execute("SET statement_timeout = '15s'")
            cur.execute("SET lock_timeout = '10s'")

            # Release both workers at approximately the same time.
            barrier.wait(timeout=15)

            if operation == "checkout":

                cur.execute("""
                    SELECT success, order_id, message
                    FROM public.place_order(%s, %s, %s)
                """, (customer_id, product_id, 7))

                success, order_id, message = cur.fetchone()

                if success:
                    return "success"

                if "out of stock" in message.lower():
                    return "refused"

                raise RuntimeError(message)

            reason, quantity = operation

            cur.execute("""
                SELECT new_stock_quantity, inventory_log_id
                FROM public.record_inventory_movement(
                    %s, %s, %s, %s
                )
            """, (
                product_id,
                reason,
                quantity,
                "Concurrent inventory movement test"
            ))

            if cur.fetchone() is None:
                raise RuntimeError("No inventory movement result returned.")

            return "success"

    except psycopg2.Error as exc:

        if (
            exc.pgcode == "P0001"
            and "Insufficient stock" in str(exc)
        ):
            return "refused"

        # Unexpected database errors must fail the test.
        raise

    finally:
        if conn is not None:
            conn.close()


def inspect_fixture(product_id):
    """Retrieve stock, audit movements and order count."""

    with connect() as conn, conn.cursor() as cur:

        cur.execute("""
            SELECT stock_quantity
            FROM products
            WHERE product_id = %s
        """, (product_id,))

        stock = cur.fetchone()[0]

        cur.execute("""
            SELECT reason, change_qty
            FROM inventory_log
            WHERE product_id = %s
            ORDER BY log_id
        """, (product_id,))

        movements = cur.fetchall()

        cur.execute("""
            SELECT COUNT(DISTINCT order_id)
            FROM order_items
            WHERE product_id = %s
        """, (product_id,))

        order_count = cur.fetchone()[0]

    return stock, movements, order_count


def cleanup_fixture(product_id):
    """Remove only records associated with the synthetic product."""

    with connect() as conn, conn.cursor() as cur:

        cur.execute("""
            SELECT DISTINCT order_id
            FROM order_items
            WHERE product_id = %s
        """, (product_id,))

        order_ids = [row[0] for row in cur.fetchall()]

        cur.execute("""
            DELETE FROM order_items
            WHERE product_id = %s
        """, (product_id,))

        if order_ids:
            cur.execute("""
                DELETE FROM orders
                WHERE order_id = ANY(%s)
            """, (order_ids,))

        cur.execute("""
            DELETE FROM inventory_log
            WHERE product_id = %s
        """, (product_id,))

        cur.execute("""
            DELETE FROM products
            WHERE product_id = %s
        """, (product_id,))


def run_round(scenario, operations, customer_id):
    """Run and verify one concurrent test round."""

    product_id = create_fixture()

    try:
        barrier = threading.Barrier(2)

        with ThreadPoolExecutor(max_workers=2) as executor:

            futures = [
                executor.submit(
                    execute_operation,
                    product_id,
                    customer_id,
                    operation,
                    barrier
                )
                for operation in operations
            ]

            results = [future.result() for future in futures]

        stock, movements, order_count = inspect_fixture(product_id)

        successes = results.count("success")
        refusals = results.count("refused")

        total_change = sum(change for _, change in movements)

        # Every successful operation must have one audit record.
        assert len(movements) == successes, (
            "Audit record count does not match successful operations."
        )

        # Recorded movements must explain the final stock balance.
        assert stock == 10 + total_change, (
            "Stock and inventory audit trail do not reconcile."
        )

        assert stock >= 0, "Negative stock detected."

        if scenario == "competing_damage":

            assert successes == 1
            assert refusals == 1
            assert stock == 3
            assert movements == [("damage", -7)]
            assert order_count == 0

        elif scenario == "concurrent_restock":

            assert successes == 2
            assert refusals == 0
            assert stock == 20
            assert movements == [
                ("restock", 5),
                ("restock", 5)
            ]
            assert order_count == 0

        elif scenario == "checkout_vs_damage":

            assert successes == 1
            assert refusals == 1
            assert stock == 3

            if results[0] == "success":
                assert movements == [("sale", -7)]
                assert order_count == 1
            else:
                assert movements == [("damage", -7)]
                assert order_count == 0

        return results[0]

    finally:
        cleanup_fixture(product_id)


def main():

    customer_id = get_customer()

    scenarios = [
        (
            "competing_damage",
            [("damage", 7), ("damage", 7)]
        ),
        (
            "concurrent_restock",
            [("restock", 5), ("restock", 5)]
        ),
        (
            "checkout_vs_damage",
            ["checkout", ("damage", 7)]
        )
    ]

    total_passed = 0

    print("KLOUD KART - CONCURRENT INVENTORY MOVEMENT TESTS")
    print("=" * 60)

    for scenario, operations in scenarios:

        print(f"\nScenario: {scenario}")

        checkout_wins = 0

        for round_number in range(1, ROUNDS + 1):

            first_result = run_round(
                scenario,
                operations,
                customer_id
            )

            total_passed += 1

            if scenario == "checkout_vs_damage":
                if first_result == "success":
                    checkout_wins += 1

            print(f"  PASS - Round {round_number}/{ROUNDS}")

        if scenario == "checkout_vs_damage":
            print(f"  Checkout wins: {checkout_wins}")
            print(f"  Damage wins: {ROUNDS - checkout_wins}")

        print(f"  Scenario passed: {ROUNDS}/{ROUNDS}")

    print("\n" + "=" * 60)
    print(f"Total rounds passed: {total_passed}/{ROUNDS * 3}")
    print("ALL CONCURRENT INVENTORY MOVEMENT TESTS PASSED.")


if __name__ == "__main__":
    main()