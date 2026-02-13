import sqlite3

conn = sqlite3.connect("flexmaster.db")
c = conn.cursor()

print("Running migration...")

# Add columns to users table
user_fields = [
    ('total_xp', 'INTEGER DEFAULT 0'),
    ('mobility_level', 'INTEGER DEFAULT 0'),
    ('activation_level', 'INTEGER DEFAULT 0'),
    ('stability_level', 'INTEGER DEFAULT 0'),
    ('power_level', 'INTEGER DEFAULT 0'),
    ('balance_level', 'INTEGER DEFAULT 0')
]

for field_name, field_type in user_fields:
    try:
        c.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_type}")
        print(f"✓ Added {field_name}")
    except:
        print(f"○ {field_name} exists")

# Add sport_category to routines
try:
    c.execute("ALTER TABLE routines ADD COLUMN sport_category TEXT DEFAULT 'General Fitness'")
    print("✓ Added sport_category")
except:
    print("○ sport_category exists")

# Create completed_exercises table
c.execute("""
CREATE TABLE IF NOT EXISTS completed_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    routine_id INTEGER,
    exercise_name TEXT,
    movement_type TEXT,
    xp_earned INTEGER DEFAULT 10,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (routine_id) REFERENCES routines(id)
)
""")
print("✓ Created completed_exercises table")

# Update existing routines with proper categories if they don't have one
try:
    c.execute("UPDATE routines SET sport_category = 'General Fitness' WHERE sport_category IS NULL OR sport_category = '' OR sport_category = 'Other'")
    print(f"✓ Updated {c.rowcount} routines with default category")
except Exception as e:
    print(f"○ Could not update routine categories: {e}")

# Recalculate levels based on existing completed exercises
print("\nRecalculating user levels...")
users = c.execute("SELECT id FROM users").fetchall()

for user in users:
    user_id = user[0]
    
    # Calculate levels for each movement type
    for movement_type in ["Mobility", "Activation", "Stability", "Power", "Balance"]:
        total_xp = c.execute(
            "SELECT COALESCE(SUM(xp_earned), 0) FROM completed_exercises WHERE user_id = ? AND movement_type = ?",
            (user_id, movement_type)
        ).fetchone()[0]
        
        # Calculate level: floor(sqrt(XP / 50))
        import math
        level = max(0, math.floor(math.sqrt(total_xp / 50))) if total_xp > 0 else 0
        
        # Update the level
        level_field = f"{movement_type.lower()}_level"
        c.execute(f"UPDATE users SET {level_field} = ? WHERE id = ?", (level, user_id))
    
    print(f"  ✓ Recalculated levels for user {user_id}")

conn.commit()
conn.close()
print("\n✅ Migration complete!")