"""
Enhanced AI Engine with Movement Type Classification
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI


@dataclass
class WarmupMove:
    name: str
    duration: int
    notes: str = ""
    movement_type: str = "Mobility"  # Mobility, Activation, Stability, Power, Balance


class AIEngine:
    """
    Enhanced AI Engine that classifies exercises by movement type
    and categorizes sports.
    """

    # Sport category mappings
    SPORT_CATEGORIES = {
        # Ball Sports
        "soccer": "Ball Sports", "football": "Ball Sports", "basketball": "Ball Sports",
        "volleyball": "Ball Sports", "tennis": "Racket Sports", "badminton": "Racket Sports",
        "table tennis": "Racket Sports", "squash": "Racket Sports", "pickleball": "Racket Sports",
        
        # Endurance Sports
        "running": "Endurance", "jogging": "Endurance", "marathon": "Endurance",
        "cycling": "Endurance", "swimming": "Endurance", "triathlon": "Endurance",
        
        # Strength Sports
        "weightlifting": "Strength Training", "powerlifting": "Strength Training",
        "bodybuilding": "Strength Training", "crossfit": "Strength Training",
        "gym": "Strength Training", "lifting": "Strength Training",
        
        # Combat Sports
        "boxing": "Combat Sports", "mma": "Combat Sports", "kickboxing": "Combat Sports",
        "martial arts": "Combat Sports", "judo": "Combat Sports", "karate": "Combat Sports",
        
        # Flexibility & Mind-Body
        "yoga": "Flexibility", "pilates": "Flexibility", "stretching": "Flexibility",
        "gymnastics": "Flexibility",
        
        # Outdoor & Adventure
        "hiking": "Outdoor", "climbing": "Outdoor", "rock climbing": "Outdoor",
        "bouldering": "Outdoor", "skiing": "Outdoor", "snowboarding": "Outdoor",
        
        # Dance & Performance
        "dance": "Dance", "ballet": "Dance", "hip hop": "Dance", "zumba": "Dance",
    }

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY environment variable.")
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def categorize_sport(self, exercise: str) -> str:
        """Categorize the sport/exercise into a category."""
        exercise_lower = exercise.lower().strip()
        
        # Direct match
        if exercise_lower in self.SPORT_CATEGORIES:
            return self.SPORT_CATEGORIES[exercise_lower]
        
        # Partial match
        for sport_key, category in self.SPORT_CATEGORIES.items():
            if sport_key in exercise_lower or exercise_lower in sport_key:
                return category
        
        # Default category
        return "Other"

    def _build_prompt(
        self,
        exercise: str,
        muscle_groups: str,
        user_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build a personalized prompt including user profile data."""
        base_prompt = (
            f"Create a safe warm-up routine for {exercise}. "
            f"Target muscle groups: {muscle_groups}. "
        )
        
        if user_data:
            age = user_data.get("age")
            fitness_level = user_data.get("fitness_level")
            preference = user_data.get("preference")
            
            if age:
                base_prompt += f"User age: {age}. "
            if fitness_level:
                base_prompt += f"Fitness level: {fitness_level}. "
            if preference:
                base_prompt += f"User preference: {preference}. "
        
        base_prompt += (
            "Return ONLY valid JSON matching the schema described in the instructions."
        )
        
        return base_prompt

    def generate_warmups(
        self,
        exercise: str,
        muscle_groups: str,
        user_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate warmup routine with movement type tags.
        
        Returns dict with:
          - exercise: str
          - sport_category: str
          - muscle_groups: str
          - warmups: list[{name, duration, notes, movement_type}]
          - safety: str
        """
        instructions = (
            "You are a sports warm-up assistant. "
            "Output must be STRICT JSON only, no markdown, no commentary.\n\n"
            "Schema:\n"
            "{\n"
            '  "warmups": [\n'
            "    {\n"
            '      "name": string,\n'
            '      "duration_seconds": integer,\n'
            '      "notes": string,\n'
            '      "movement_type": string  // One of: Mobility, Activation, Stability, Power, Balance\n'
            "    }\n"
            "  ],\n"
            '  "safety": string\n'
            "}\n\n"
            "Rules:\n"
            "- Provide 6 to 10 warmups.\n"
            "- Classify each exercise by movement type:\n"
            "  * Mobility: Joint range of motion, dynamic stretches\n"
            "  * Activation: Muscle engagement, neural activation\n"
            "  * Stability: Core control, balance foundations\n"
            "  * Power: Explosive movements, plyometrics\n"
            "  * Balance: Coordination, proprioception\n"
            "- Include a variety of movement types for comprehensive warm-up.\n"
            "- Use realistic durations; total time 6-12 minutes.\n"
            "- Personalize based on user's age, fitness level, and preferences.\n"
            "- No medical claims; advise consulting professionals when needed.\n"
        )

        resp = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=self._build_prompt(
                exercise=exercise,
                muscle_groups=muscle_groups,
                user_data=user_data
            ),
        )

        raw_text = (resp.output_text or "").strip()
        routine_obj, parse_error = self._safe_json_load(raw_text)

        warmups: List[Dict[str, Any]] = []
        safety = ""

        if isinstance(routine_obj, dict):
            safety = str(routine_obj.get("safety", "")).strip()
            items = routine_obj.get("warmups", [])
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    n = str(item.get("name", "")).strip()
                    d = item.get("duration_seconds", item.get("duration", 0))
                    try:
                        d_int = int(d)
                    except Exception:
                        d_int = 0
                    notes = str(item.get("notes", "")).strip()
                    movement_type = str(item.get("movement_type", "Mobility")).strip()
                    
                    # Validate movement type
                    valid_types = ["Mobility", "Activation", "Stability", "Power", "Balance"]
                    if movement_type not in valid_types:
                        movement_type = "Mobility"
                    
                    if n and d_int > 0:
                        warmups.append({
                            "name": n,
                            "duration": d_int,
                            "notes": notes,
                            "movement_type": movement_type
                        })

        if not warmups:
            return {
                "exercise": exercise,
                "sport_category": self.categorize_sport(exercise),
                "muscle_groups": muscle_groups,
                "warmups": [],
                "safety": "",
                "raw": raw_text,
                "error": parse_error or "Could not parse the model output.",
            }

        return {
            "exercise": exercise,
            "sport_category": self.categorize_sport(exercise),
            "muscle_groups": muscle_groups,
            "warmups": warmups,
            "safety": safety,
            "raw": raw_text,
            "error": None,
        }

    @staticmethod
    def _safe_json_load(text: str) -> Tuple[Optional[Any], Optional[str]]:
        if not text:
            return None, "Empty model output."
        try:
            return json.loads(text), None
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate), None
            except Exception as e:
                return None, f"JSON parse error: {e}"
        return None, "No JSON object found in model output."