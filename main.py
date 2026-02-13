from __future__ import annotations

import json
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

from ai_engine import AIEngine

app = Flask(__name__, template_folder=".")
app.secret_key = "super-secret-key"  # change later for production

# Add custom Jinja filter for JSON parsing
@app.template_filter('fromjson')
def fromjson_filter(value):
    """Parse JSON string in Jinja templates"""
    if isinstance(value, str):
        return json.loads(value)
    return value

DB_NAME = "flexmaster.db"

MODEL = os.environ.get("FLEXMASTER_MODEL", "gpt-4.1-mini")
engine = None


def get_engine() -> AIEngine:
    global engine
    if engine is None:
        engine = AIEngine(model=MODEL)
    return engine


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------- XP & LEVELING SYSTEM --------------------

def calculate_level(xp):
    """Calculate level from XP (exponential growth)"""
    # Level = floor(sqrt(XP / 50))
    import math
    if xp <= 0:
        return 0
    return max(0, math.floor(math.sqrt(xp / 50)))


def xp_for_next_level(current_level):
    """Calculate XP needed for next level"""
    return (current_level + 1) ** 2 * 50


def update_movement_level(user_id, movement_type, xp_amount):
    """Update user's movement type level based on XP"""
    conn = get_db()
    
    # Get current XP for this movement type
    current_xp = conn.execute(
        "SELECT COALESCE(SUM(xp_earned), 0) as total FROM completed_exercises WHERE user_id = ? AND movement_type = ?",
        (user_id, movement_type)
    ).fetchone()["total"]
    
    # Calculate new level
    new_level = calculate_level(current_xp)
    
    # Update the level in users table
    level_field = f"{movement_type.lower()}_level"
    conn.execute(
        f"UPDATE users SET {level_field} = ? WHERE id = ?",
        (new_level, user_id)
    )
    
    conn.commit()
    conn.close()


def add_xp(user_id, movement_type, xp_amount):
    """Add XP to user's specific movement type level"""
    conn = get_db()
    
    # Add total XP
    conn.execute(
        "UPDATE users SET total_xp = total_xp + ? WHERE id = ?",
        (xp_amount, user_id)
    )
    
    conn.commit()
    conn.close()
    
    # Update the movement-specific level
    update_movement_level(user_id, movement_type, xp_amount)


def save_completed_exercise(user_id, routine_id, exercise_name, movement_type, xp_earned):
    """Save a completed exercise to track progress"""
    conn = get_db()
    conn.execute(
        """
        INSERT INTO completed_exercises 
        (user_id, routine_id, exercise_name, movement_type, xp_earned)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, routine_id, exercise_name, movement_type, xp_earned)
    )
    conn.commit()
    conn.close()


# -------------------- AUTH ROUTES --------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        age = request.form["age"]
        fitness = request.form["fitness_level"]
        preference = request.form["preference"]

        try:
            conn = get_db()
            conn.execute(
                """
                INSERT INTO users (username, password, age, fitness_level, preference)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, password, age, fitness, preference),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return render_template("signup.html", error="Username already exists")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password),
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------- MAIN APP --------------------

@app.route("/", methods=["GET", "POST"])
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("index.html", username=session["username"])

    exercise = (request.form.get("exercise") or "").strip()
    muscle_groups = (request.form.get("muscle_groups") or "").strip()

    if not exercise or not muscle_groups:
        return render_template(
            "index.html",
            error="Please enter both the exercise name and target muscle groups.",
            exercise=exercise,
            muscle_groups=muscle_groups,
            username=session["username"],
        )

    # Get user data for personalization
    user = get_user(session["user_id"])
    user_data = {
        "age": user["age"] if user else None,
        "fitness_level": user["fitness_level"] if user else None,
        "preference": user["preference"] if user else None,
    }

    result = get_engine().generate_warmups(
        exercise=exercise,
        muscle_groups=muscle_groups,
        user_data=user_data
    )

    # Save routine to database if generation was successful
    routine_id = None
    if result.get("warmups") and not result.get("error"):
        routine_id = save_routine(session["user_id"], result)

    # Redirect to interactive routine page
    if routine_id:
        return redirect(url_for("interactive_routine", routine_id=routine_id))

    return render_template(
        "results.html",
        exercise=result.get("exercise", exercise),
        muscle_groups=result.get("muscle_groups", muscle_groups),
        warmups=result.get("warmups", []),
        safety=result.get("safety", ""),
        error=result.get("error"),
        raw=result.get("raw", ""),
        username=session["username"],
    )


def get_user(user_id):
    """Get user information by user_id"""
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return user


def save_routine(user_id, routine_data):
    """Save a generated routine to the database"""
    conn = get_db()
    routine_json = json.dumps(routine_data)
    
    # Extract or infer sport category
    sport_category = routine_data.get("sport_category", "General Fitness")
    
    # If no category provided, try to infer from exercise name
    if sport_category == "Other" or not sport_category:
        exercise_name = routine_data.get("exercise", "").lower()
        
        # Category mapping based on exercise keywords
        category_keywords = {
            "Running": ["running", "run", "sprint", "jog", "marathon", "5k", "10k"],
            "Weightlifting": ["squat", "deadlift", "bench press", "overhead press", "lifting", "weights", "barbell", "dumbbell"],
            "Cycling": ["cycling", "bike", "biking", "spin"],
            "Swimming": ["swimming", "swim", "freestyle", "backstroke", "breaststroke"],
            "Tennis": ["tennis", "serve", "forehand", "backhand"],
            "Basketball": ["basketball", "jump shot", "layup", "dunk", "free throw"],
            "Soccer": ["soccer", "football", "kick", "dribbling"],
            "Yoga": ["yoga", "downward dog", "warrior", "tree pose", "sun salutation"],
            "Martial Arts": ["martial arts", "karate", "taekwondo", "judo", "boxing", "kickboxing", "mma"],
            "Rock Climbing": ["climbing", "bouldering", "rock climbing"],
            "CrossFit": ["crossfit", "wod", "amrap", "emom"],
            "Pilates": ["pilates"],
            "Dance": ["dance", "ballet", "hip hop", "contemporary"],
            "Golf": ["golf", "swing", "putt", "drive"],
            "Volleyball": ["volleyball", "spike", "serve", "bump"],
        }
        
        # Check for keyword matches
        for category, keywords in category_keywords.items():
            if any(keyword in exercise_name for keyword in keywords):
                sport_category = category
                break
        
        # If still no category, default to General Fitness
        if not sport_category or sport_category == "Other":
            sport_category = "General Fitness"
    
    cursor = conn.execute(
        "INSERT INTO routines (user_id, routine_json, sport_category) VALUES (?, ?, ?)",
        (user_id, routine_json, sport_category)
    )
    routine_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return routine_id


def get_routines(user_id):
    """Get all routines for a specific user"""
    conn = get_db()
    routines = conn.execute(
        "SELECT routine_json, id, created_at, sport_category FROM routines WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return routines


def get_user_stats(user_id):
    """Get user statistics for gamification"""
    conn = get_db()
    
    # Get total routines
    total_routines = conn.execute(
        "SELECT COUNT(*) as count FROM routines WHERE user_id = ?",
        (user_id,)
    ).fetchone()["count"]
    
    # Get total completed exercises
    total_exercises = conn.execute(
        "SELECT COUNT(*) as count FROM completed_exercises WHERE user_id = ?",
        (user_id,)
    ).fetchone()["count"]
    
    # Get user XP and levels
    user = conn.execute(
        "SELECT total_xp, mobility_level, activation_level, stability_level, power_level, balance_level FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    
    # Get XP per movement type and calculate levels dynamically
    movement_xp = {}
    calculated_levels = {}
    for movement_type in ["Mobility", "Activation", "Stability", "Power", "Balance"]:
        xp = conn.execute(
            "SELECT COALESCE(SUM(xp_earned), 0) as total FROM completed_exercises WHERE user_id = ? AND movement_type = ?",
            (user_id, movement_type)
        ).fetchone()["total"]
        movement_xp[movement_type.lower()] = xp
        calculated_levels[movement_type.lower()] = calculate_level(xp)
    
    conn.close()
    
    return {
        "total_xp": user["total_xp"] or 0,
        "total_routines": total_routines,
        "total_exercises": total_exercises,
        "levels": calculated_levels,  # Use calculated levels instead of stored ones
        "movement_xp": movement_xp
    }


@app.route("/profile")
def profile():
    """Display user profile with stats and routines"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user_id"]
    user = get_user(user_id)
    routines = get_routines(user_id)
    stats = get_user_stats(user_id)
    
    # Group routines by category
    categories = {}
    for routine in routines:
        data = json.loads(routine["routine_json"])
        category = data.get("sport_category", "General Fitness")
        if not category or category == "Other":
            category = "General Fitness"
        if category not in categories:
            categories[category] = []
        categories[category].append(routine)
    
    return render_template(
        "profile.html",
        user=user,
        routines=routines,
        categories=categories,
        stats=stats,
        username=session["username"]
    )


@app.route("/routine/<int:routine_id>")
def view_routine(routine_id):
    """View a specific saved routine (static view)"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    conn = get_db()
    routine = conn.execute(
        "SELECT routine_json, user_id FROM routines WHERE id = ?",
        (routine_id,)
    ).fetchone()
    conn.close()
    
    if not routine or routine["user_id"] != session["user_id"]:
        return redirect(url_for("profile"))
    
    routine_data = json.loads(routine["routine_json"])
    
    return render_template(
        "results.html",
        exercise=routine_data.get("exercise", ""),
        muscle_groups=routine_data.get("muscle_groups", ""),
        warmups=routine_data.get("warmups", []),
        safety=routine_data.get("safety", ""),
        error=routine_data.get("error"),
        raw=routine_data.get("raw", ""),
        username=session["username"],
        routine_id=routine_id
    )


@app.route("/interactive/<int:routine_id>")
def interactive_routine(routine_id):
    """Interactive routine completion page with checklist"""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    conn = get_db()
    routine = conn.execute(
        "SELECT routine_json, user_id FROM routines WHERE id = ?",
        (routine_id,)
    ).fetchone()
    conn.close()
    
    if not routine or routine["user_id"] != session["user_id"]:
        return redirect(url_for("profile"))
    
    routine_data = json.loads(routine["routine_json"])
    
    # Ensure all warmups have movement_type (for older routines)
    warmups = routine_data.get("warmups", [])
    for warmup in warmups:
        if "movement_type" not in warmup:
            warmup["movement_type"] = "Mobility"  # Default
    
    return render_template(
        "interactive_routine.html",
        routine_id=routine_id,
        exercise=routine_data.get("exercise", ""),
        muscle_groups=routine_data.get("muscle_groups", ""),
        warmups=warmups,
        safety=routine_data.get("safety", ""),
        username=session["username"]
    )


@app.route("/api/complete_exercise", methods=["POST"])
def complete_exercise():
    """API endpoint to mark an exercise as complete and award XP"""
    if "user_id" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    routine_id = data.get("routine_id")
    exercise_name = data.get("exercise_name")
    movement_type = data.get("movement_type")
    xp_earned = data.get("xp_earned", 10)
    
    # Save completed exercise
    save_completed_exercise(
        session["user_id"],
        routine_id,
        exercise_name,
        movement_type,
        xp_earned
    )
    
    # Add XP to user and update level
    add_xp(session["user_id"], movement_type, xp_earned)
    
    return jsonify({"success": True, "xp_earned": xp_earned})


@app.route("/api/complete_routine", methods=["POST"])
def complete_routine():
    """API endpoint to complete entire routine and award bonus XP"""
    if "user_id" not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    routine_id = data.get("routine_id")
    bonus_xp = data.get("bonus_xp", 50)
    
    # Award bonus XP to total
    conn = get_db()
    conn.execute(
        "UPDATE users SET total_xp = total_xp + ? WHERE id = ?",
        (bonus_xp, session["user_id"])
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "bonus_xp": bonus_xp})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)