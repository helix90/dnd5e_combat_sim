"""Check spell actions in batch simulations."""

import sqlite3

# Direct database access
conn = sqlite3.connect('dnd5e_sim.db')
conn.row_factory = sqlite3.Row

print("=" * 70)
print("CHECKING BATCH SIMULATIONS FOR SPELL ACTIONS")
print("=" * 70)

# Get recent batch simulations
cursor = conn.execute('''
    SELECT id, batch_name, created_at
    FROM batch_simulations
    ORDER BY id DESC
    LIMIT 5
''')
batches = cursor.fetchall()

print(f"\nFound {len(batches)} recent batch simulations:\n")

for batch in batches:
    batch_id = batch['id']
    batch_name = batch['batch_name']
    created_at = batch['created_at']

    print(f"Batch ID {batch_id}: {batch_name}")
    print(f"  Created: {created_at}")

    # Get simulations in this batch
    cursor = conn.execute('''
        SELECT simulation_id
        FROM batch_simulation_runs
        WHERE batch_id = ?
    ''', (batch_id,))
    sim_ids = [row['simulation_id'] for row in cursor.fetchall()]

    print(f"  Total simulations: {len(sim_ids)}")

    if not sim_ids:
        print("  (No simulations found)\n")
        continue

    # Check first simulation in detail
    first_sim = sim_ids[0]

    # Count all action types
    cursor = conn.execute('''
        SELECT action_type, COUNT(*) as count
        FROM combat_logs
        WHERE simulation_id = ?
        GROUP BY action_type
    ''', (first_sim,))
    action_counts = cursor.fetchall()

    print(f"\n  First simulation (ID {first_sim}) action breakdown:")
    for row in action_counts:
        print(f"    {row['action_type']}: {row['count']}")

    # Get example spell actions if any
    cursor = conn.execute('''
        SELECT round_number, character_name, result
        FROM combat_logs
        WHERE simulation_id = ? AND action_type = 'spell'
        LIMIT 3
    ''', (first_sim,))
    spell_examples = cursor.fetchall()

    if spell_examples:
        print(f"\n  Example spell actions:")
        for spell in spell_examples:
            result_preview = spell['result'][:60] if spell['result'] else ''
            print(f"    Round {spell['round_number']}: {spell['character_name']} - {result_preview}")
    else:
        print(f"\n  ✗ NO SPELL ACTIONS FOUND")

    print()

conn.close()

print("=" * 70)
print("RECOMMENDATION")
print("=" * 70)
print("""
If batch simulations show 0 spell actions, they were likely created
BEFORE the bug fixes. Try creating a NEW batch simulation to verify
the fixes work correctly.
""")
