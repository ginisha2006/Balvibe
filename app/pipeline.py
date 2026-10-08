from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audio import concatenate_wavs, wav_duration_ms
from .config import Settings
from .db import Database
from .bhashini import translate_text_bhashini
from .providers import call_groq_json, synthesize, translate_text_sarvam

AGE_BANDS = {"4-5", "6-8", "9-11", "9-12"}
CHARACTER_TYPES = {"animal", "robot", "creature"}
TRIAL_PHASES = {"demonstration", "practice", "formal"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reconcile(items: list[dict[str, Any]], target: float) -> list[dict[str, Any]]:
    if not items:
        raise ValueError("Cannot reconcile an empty list.")
    total = sum(float(item.get("durationSeconds", 0)) for item in items)
    if total <= 0:
        raise ValueError("Generated durations must be positive.")
    scale = target / total
    out = [dict(item, durationSeconds=float(item["durationSeconds"]) * scale) for item in items]
    out[-1]["durationSeconds"] += target - sum(item["durationSeconds"] for item in out)
    return out


def _ensure_closing(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sections:
        return sections
    last = sections[-1]
    if re.search(r"closing|finish|goodbye|ending|wrap", str(last.get("title", "")), re.I):
        return sections
    if float(last.get("durationSeconds", 0)) < 4:
        return sections
    duration = min(10.0, max(2.0, float(last["durationSeconds"]) / 3))
    copied = copy.deepcopy(sections)
    copied[-1]["durationSeconds"] -= duration
    copied.append({
        "sectionOrder": len(copied) + 1,
        "title": "Closing",
        "purpose": "Briefly finish the activity.",
        "durationSeconds": duration,
        "requiredContent": ["Give a short goodbye without correctness feedback."],
    })
    return copied


def validate_storyline_flow(flow: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(flow, dict):
        raise ValueError("Storyline flow must be a JSON object.")
    age = flow.get("ageBand")
    if age not in AGE_BANDS:
        raise ValueError("Unsupported age band.")
    target = flow.get("targetDurationSeconds")
    if not isinstance(target, int) or not (30 <= target <= 3600):
        raise ValueError("targetDurationSeconds must be an integer from 30 to 3600.")
    title = str(flow.get("title", "")).strip()
    if not title:
        raise ValueError("Storyline flow requires a title.")
    premise = str(flow.get("narrativePremise", "")).strip()
    if not premise:
        raise ValueError("Storyline flow requires a narrativePremise.")
    setting = str(flow.get("setting", "")).strip()
    if not setting:
        raise ValueError("Storyline flow requires one consistent setting.")
    flow["setting"] = setting

    char = flow.get("leadCharacter")
    if not isinstance(char, dict):
        raise ValueError("Storyline flow requires a leadCharacter object.")
    char_name = str(char.get("name", "")).strip()
    if not char_name:
        raise ValueError("leadCharacter requires a non-empty name.")
    char_type = str(char.get("characterType", "")).lower()
    if char_type not in CHARACTER_TYPES:
        char["characterType"] = "robot"

    gamification = flow.get("gamificationElements")
    if not isinstance(gamification, dict):
        flow["gamificationElements"] = {
            "gameTheme": "Interactive Cognitive Adventure",
            "playerRole": "Player Detective",
            "challengeType": "Observation Challenge",
            "engagementHook": "Explore and discover clues",
            "rewardFeedbackPolicy": "Positive encouragement only",
        }

    steps = flow.get("flowSteps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Storyline flow must contain flowSteps.")

    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError("Each flow step must be an object.")
        step["stepNumber"] = idx
        if not str(step.get("title", "")).strip():
            step["title"] = f"Flow Step {idx}"
        if float(step.get("durationSeconds", 0)) <= 0:
            step["durationSeconds"] = 5.0
        if not str(step.get("gamifiedObjective", "")).strip():
            step["gamifiedObjective"] = "Present this part of the game quest."
        if not str(step.get("protocolRule", "")).strip():
            step["protocolRule"] = "Preserve researcher experiment protocol."
        step["setting"] = setting

    flow["flowSteps"] = _reconcile(steps, target)
    return flow


def _infer_character_type(char_str: str) -> str:
    s = char_str.lower()
    if any(w in s for w in ["robot", "bot", "droid", "cyborg", "machine", "mech"]):
        return "robot"
    if any(w in s for w in ["rabbit", "bunny", "bear", "fox", "cat", "dog", "owl", "monkey", "lion", "tiger", "bird", "deer", "mouse", "elephant", "frog", "panda"]):
        return "animal"
    return "creature"


def demo_storyline_flow(
    instruction: str,
    age_band: str,
    duration: int,
    lead_character: str | None = None,
    setting: str | None = None,
    story_idea: str | None = None,
) -> dict[str, Any]:
    if lead_character and lead_character.strip():
        c_name = lead_character.strip()
        c_type = _infer_character_type(c_name)
        char_profile = {
            "name": c_name,
            "characterType": c_type,
            "role": "Playful Quest Companion",
            "personality": "Warm, encouraging, and adventurous",
        }
    else:
        char_profile = {
            "4-5": {"name": "Barnaby", "characterType": "animal", "role": "Playful Forest Guide", "personality": "Warm, gentle, encouraging"},
            "6-8": {"name": "Pico", "characterType": "robot", "role": "Cosmic Explorer Robot", "personality": "Curious, lively, supportive"},
            "9-11": {"name": "Gizmo", "characterType": "creature", "role": "Mystery Lab Detective", "personality": "Clever, energetic, friendly"},
            "9-12": {"name": "Gizmo", "characterType": "creature", "role": "Mystery Lab Detective", "personality": "Clever, energetic, friendly"},
        }.get(age_band, {"name": "Pico", "characterType": "robot", "role": "Explorer Robot", "personality": "Curious and lively"})

    place = setting.strip() if setting and setting.strip() else ("lantern lit forest" if age_band == "4-5" else "star base lab")
    custom_idea = story_idea.strip() if story_idea and story_idea.strip() else None

    if custom_idea:
        title = f"{char_profile['name']}'s Adventure: {custom_idea.title()}"
        premise = f"Join {char_profile['name']} in the {place} on a quest to {custom_idea}. Together, players solve observation challenges across every game stage."
        game_theme = f"Quest in {place.title()}"
    else:
        theme_profile = {
            "4-5": {
                "title": f"{char_profile['name']}'s Magical Number Garden",
                "narrativePremise": f"Step into {char_profile['name']}'s sunny garden in the {place} where glowing number blossoms peek out. Help {char_profile['name']} notice which magical blossom hides away!",
                "gameTheme": "Magical Garden Bloom Quest",
            },
            "6-8": {
                "title": f"{char_profile['name']}'s Cosmic Number Vault",
                "narrativePremise": f"Embark on an adventure with {char_profile['name']} in the {place} to power up star beacons. Watch glowing numbers flash and spot which beacon disappears!",
                "gameTheme": "Star Base Vault Adventure",
            },
            "9-11": {
                "title": f"{char_profile['name']}'s Quantum Codebreaker Mission",
                "narrativePremise": f"Join secret agent {char_profile['name']} in the {place}. Crack code grids by tracking which cyber-number vanished from the encrypted terminal screen.",
                "gameTheme": "High-Tech Cypher Agency",
            },
            "9-12": {
                "title": f"{char_profile['name']}'s Quantum Codebreaker Mission",
                "narrativePremise": f"Join secret agent {char_profile['name']} in the {place}. Crack code grids by tracking which cyber-number vanished from the encrypted terminal screen.",
                "gameTheme": "High-Tech Cypher Agency",
            },
        }.get(age_band, {
            "title": f"{char_profile['name']}'s Number Adventure",
            "narrativePremise": f"Join {char_profile['name']} on an exciting discovery game in {place}.",
            "gameTheme": "Playful Discovery Quest",
        })
        title = theme_profile["title"]
        premise = theme_profile["narrativePremise"]
        game_theme = theme_profile["gameTheme"]

    flow_steps = [
        {
            "stepNumber": 1,
            "title": "Mission Briefing & Rules",
            "actType": "intro",
            "durationSeconds": 15,
            "gamifiedObjective": f"{char_profile['name']} welcomes the player in {place}, introduces the game world, and explains the observation rule.",
            "protocolRule": "Introduce activity instructions and ask participant to watch attentively.",
            "visualDescription": f"{char_profile['name']} stands in the center of {place} waving and explaining the game.",
        },
        {
            "stepNumber": 2,
            "title": "Training Round (Practice Quest)",
            "actType": "practice",
            "durationSeconds": 30,
            "gamifiedObjective": "A hands-on practice round showing how the numbers appear and one disappears.",
            "protocolRule": "One practice trial: display numbers for 2s, response window 5s.",
            "visualDescription": f"The same number display appears in {place}; one number vanishes with a sparkling cue.",
        },
        {
            "stepNumber": 3,
            "title": "Main Challenge (Formal Trials)",
            "actType": "formal_trials",
            "durationSeconds": 60,
            "gamifiedObjective": "The player completes the official challenge rounds in the same setting and on the same display.",
            "protocolRule": "Formal experimental trials with strictly preserved timings and stimuli.",
            "visualDescription": f"High-energy number challenges on the same display in {place}; only the number set changes.",
        },
        {
            "stepNumber": 4,
            "title": "Mission Wrap-up & Farewell",
            "actType": "closing",
            "durationSeconds": 15,
            "gamifiedObjective": f"{char_profile['name']} celebrates finishing the mission, thanks the player, and waves goodbye.",
            "protocolRule": "Neutral conclusion without disclosing participant accuracy.",
            "visualDescription": f"{char_profile['name']} delivers a cheerful closing animation with glowing quest badges.",
        },
    ]
    flow_steps = _reconcile(flow_steps, duration)

    return validate_storyline_flow({
        "title": title,
        "narrativePremise": premise,
        "setting": place,
        "ageBand": age_band,
        "targetDurationSeconds": duration,
        "language": "en-US",
        "gamificationElements": {
            "gameTheme": game_theme,
            "playerRole": "Junior Detective Explorer",
            "challengeType": "Observation & Memory Challenge",
            "engagementHook": f"Help {char_profile['name']} find the missing clues in {place}!",
            "rewardFeedbackPolicy": "Positive encouragement only without correctness feedback",
        },
        "leadCharacter": char_profile,
        "flowSteps": flow_steps,
        "sourceInstruction": instruction,
        "generator": "demo-deterministic",
    })


def generate_storyline_flow(
    instruction: str,
    age_band: str,
    duration: int,
    settings: Settings,
    lead_character: str | None = None,
    setting: str | None = None,
    story_idea: str | None = None,
) -> dict[str, Any]:
    if age_band not in AGE_BANDS:
        raise ValueError("ageBand must be one of 4-5, 6-8, 9-11, 9-12.")
    if not isinstance(duration, int) or not 30 <= duration <= 3600:
        raise ValueError("duration must be a whole number from 30 to 3600 seconds.")
    if len(instruction.strip()) < 10:
        raise ValueError("Please provide a more complete experiment instruction.")
    if settings.demo_mode:
        return demo_storyline_flow(instruction, age_band, duration, lead_character, setting, story_idea)

    age_rule = {
        "4-5": "Use playful animal or magic themes, very short simple sentences, and concrete familiar ideas.",
        "6-8": "Use robot explorer or adventure puzzle themes, playful everyday vocabulary, and active quest rules.",
        "9-11": "Use secret agent, sci-fi mystery, or codebreaker themes, with crisp school-age vocabulary.",
        "9-12": "Use secret agent, sci-fi mystery, or codebreaker themes, with crisp school-age vocabulary.",
    }.get(age_band, "Use clear child-friendly vocabulary.")

    story_directions = []
    if lead_character and lead_character.strip():
        story_directions.append(f"- Preferred Lead Companion Character: {lead_character.strip()}")
    if setting and setting.strip():
        story_directions.append(f"- Where it happens / Setting: {setting.strip()}")
    if story_idea and story_idea.strip():
        story_directions.append(f"- Custom Story Idea / Premise: {story_idea.strip()}")

    system = (
        f"You are an educational video game designer for child-facing experiments aged {age_band}. {age_rule} "
        f"The total video duration is {duration} seconds. "
        "Your task is to transform the researcher's cognitive experiment instructions into an engaging, gamified storyline flow of the entire video. "
        "Gamify the whole experiment for the video: give it a playful adventure/game theme, a friendly non-human lead companion character, "
        "compelling game mechanics, and a step-by-step video flow that maps cleanly to the experimental protocol. "
        "If user story directions are provided (lead character, where it happens, or story idea), you MUST honor and weave them into the storyline. "
        "If any field is omitted or blank, invent a creative, engaging theme tailored to the target age. "
        "Continuity is mandatory: choose one physical setting and keep the character in that exact setting for the entire video, from opening through closing. "
        "Do not move to a new place, introduce a second location, or describe travel between locations. "
        "Keep the researcher's core experiment task the same in every step; the adventure theme is only a wrapper, not a replacement for the task. "
        "Practice and formal rounds repeat the same activity in the same place and on the same display; only the trial stimuli may change. "
        "Preserve all experiment rules, stimuli timings, exposure durations, practice rounds, and formal trial counts. "
        "Do not invent correctness feedback or reveal participant scores. "
        "Return ONLY one JSON object with: "
        "- 'title': catchy video adventure title "
        "- 'narrativePremise': 2-3 sentences explaining the overarching gamified storyline "
        "- 'setting': one specific physical place used unchanged throughout every scene "
        "- 'gamificationElements': { 'gameTheme': string, 'playerRole': string, 'challengeType': string, 'engagementHook': string, 'rewardFeedbackPolicy': string } "
        "- 'leadCharacter': { 'name': string, 'characterType': 'animal'|'robot'|'creature', 'role': string, 'personality': string } "
        "- 'flowSteps': array of 4 to 6 objects. Each: { 'stepNumber': int, 'title': string, 'actType': 'intro'|'practice'|'formal_trials'|'closing', "
        "'durationSeconds': float, 'gamifiedObjective': string, 'protocolRule': string, 'setting': string, 'visualDescription': string }. "
        "Every flow step's setting and visualDescription must remain in the single setting; vary only character actions and trial stimuli. "
        f"The sum of durations across all flowSteps must be close to {duration} seconds."
    )

    if story_directions:
        direction_text = "\n".join(story_directions)
        user_prompt = (
            f'Researcher experiment instructions:\n"""\n{instruction}\n"""\n\n'
            f'User Optional Story Direction:\n{direction_text}\n\n'
            'Please build the gamified storyline incorporating these user choices.'
        )
    else:
        user_prompt = (
            f'Researcher instructions:\n"""\n{instruction}\n"""\n\n'
            f'(No custom story direction provided: please invent an age-appropriate gamified theme, setting, and lead character)'
        )

    result = call_groq_json(
        system,
        user_prompt,
        settings,
        max_tokens=1400,
    )

    result["ageBand"] = age_band
    result["targetDurationSeconds"] = duration
    result["language"] = "en-US"
    result["sourceInstruction"] = instruction
    result["generator"] = f"groq:{settings.groq_model}:storyline-flow"
    if setting and setting.strip():
        result["setting"] = setting.strip()
    return validate_storyline_flow(result)


def validate_storyline(storyline: dict[str, Any]) -> dict[str, Any]:
    age = storyline.get("ageBand")
    if age not in AGE_BANDS:
        raise ValueError("Unsupported age band.")
    target = storyline.get("targetDurationSeconds")
    if not isinstance(target, int) or not (30 <= target <= 3600):
        raise ValueError("targetDurationSeconds must be an integer from 30 to 3600.")
    sections = storyline.get("plannedSections")
    scenes = storyline.get("scenes")
    if not isinstance(sections, list) or not sections or not isinstance(scenes, list) or not scenes:
        raise ValueError("Storyline must contain plannedSections and scenes.")
    setting = str(storyline.get("setting", "")).strip()
    primary: str | None = None
    seen_orders: set[int] = set()
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError("Each scene must be an object.")
        order = scene.get("sceneOrder")
        if not isinstance(order, int) or order < 1 or order in seen_orders:
            raise ValueError("sceneOrder must be unique positive integers.")
        seen_orders.add(order)
        scene["sceneOrder"] = index
        if float(scene.get("durationSeconds", 0)) <= 0:
            raise ValueError(f"Scene {index} needs a positive duration.")
        if scene.get("characterType") not in CHARACTER_TYPES:
            raise ValueError(f"Scene {index} has an unsupported characterType.")
        for key in ("characterName", "characterState", "visualAssetTag", "audioScript", "sourceText"):
            if not str(scene.get(key, "")).strip():
                raise ValueError(f"Scene {index} is missing {key}.")
        if setting:
            scene["setting"] = setting
        if primary is None:
            primary = str(scene["characterName"])
        elif scene["characterName"] != primary:
            raise ValueError("The lead character must remain consistent across scenes.")
        trial = scene.get("trial")
        if trial is not None:
            if not isinstance(trial, dict) or trial.get("phase") not in TRIAL_PHASES:
                raise ValueError(f"Scene {index} has invalid trial metadata.")
            nums = trial.get("displayNumbers")
            missing = trial.get("missingNumber")
            if not isinstance(nums, list) or missing not in nums:
                raise ValueError(f"Scene {index} missingNumber must be in displayNumbers.")
        if re.search(r"(you|your answer|the child).*(got it right|answered correctly|was correct)", scene["audioScript"], re.I):
            raise ValueError(f"Scene {index} makes a participant-outcome claim.")
    return storyline


def demo_script_from_storyline(storyline_flow: dict[str, Any], instruction: str, duration: int) -> dict[str, Any]:
    char = storyline_flow.get("leadCharacter", {})
    char_name = char.get("name", "Pico")
    char_type = char.get("characterType", "robot")
    if char_type not in CHARACTER_TYPES:
        char_type = "robot"

    title = storyline_flow.get("title", "Number Quest")
    setting = storyline_flow["setting"]

    sections = [
        {
            "sectionOrder": step["stepNumber"],
            "title": step["title"],
            "purpose": step["gamifiedObjective"],
            "durationSeconds": step["durationSeconds"],
            "requiredContent": [step.get("protocolRule", "Preserve experiment protocol.")],
        }
        for step in storyline_flow["flowSteps"]
    ]
    sections = _ensure_closing(_reconcile(sections, duration))

    scenes = [
        {
            "sceneOrder": 1,
            "durationSeconds": 15,
            "characterType": char_type,
            "characterName": char_name,
            "characterState": "waving",
            "visualAssetTag": "quest_welcome",
            "setting": setting,
            "audioScript": f"Hello adventurer! I am {char_name}. Welcome to our {title}, right here in {setting}! Look at the screen and listen carefully.",
            "sourceText": f"Hello adventurer! I am {char_name}. Welcome to our {title}! Look at the screen and listen carefully.",
        },
        {
            "sceneOrder": 2,
            "durationSeconds": 25,
            "characterType": char_type,
            "characterName": char_name,
            "characterState": "pointing",
            "visualAssetTag": "practice_numbers",
            "setting": setting,
            "audioScript": f"Let's practice right here in {setting}. Look at the numbers on this screen. [PAUSE 2 seconds] Now tell me what is missing.",
            "sourceText": "Let's do a practice round! Look at the numbers. [PAUSE 2 seconds] Now tell me what is missing.",
            "trial": {
                "trialNumber": 1,
                "phase": "practice",
                "displayNumbers": [2, 4, 6, 8, 1, 3],
                "missingNumber": 8,
                "displayDurationSeconds": 2,
                "responseWindowSeconds": 5,
            },
        },
        {
            "sceneOrder": 3,
            "durationSeconds": 30,
            "characterType": char_type,
            "characterName": char_name,
            "characterState": "attentive",
            "visualAssetTag": "formal_trial_1",
            "setting": setting,
            "audioScript": f"Now let's keep playing the same number game here in {setting}. Watch this screen carefully. [PAUSE 2 seconds] Which number disappeared?",
            "sourceText": "Now we start the real challenge rounds! Watch the screen carefully. [PAUSE 2 seconds] Which number disappeared?",
            "trial": {
                "trialNumber": 2,
                "phase": "formal",
                "displayNumbers": [1, 5, 9, 3, 7, 2],
                "missingNumber": 5,
                "displayDurationSeconds": 2,
                "responseWindowSeconds": 5,
            },
        },
        {
            "sceneOrder": 4,
            "durationSeconds": 30,
            "characterType": char_type,
            "characterName": char_name,
            "characterState": "pointing",
            "visualAssetTag": "formal_trial_2",
            "setting": setting,
            "audioScript": f"Here is the next round of the same game on this screen in {setting}. Look at the numbers. [PAUSE 2 seconds] Tell me the missing number.",
            "sourceText": "Here is our next challenge chamber. Look at the numbers. [PAUSE 2 seconds] Tell me the missing number.",
            "trial": {
                "trialNumber": 3,
                "phase": "formal",
                "displayNumbers": [6, 4, 8, 2, 9, 1],
                "missingNumber": 4,
                "displayDurationSeconds": 2,
                "responseWindowSeconds": 5,
            },
        },
        {
            "sceneOrder": 5,
            "durationSeconds": 20,
            "characterType": char_type,
            "characterName": char_name,
            "characterState": "celebrating",
            "visualAssetTag": "closing_victory",
            "setting": setting,
            "audioScript": f"Great job playing the number game with me here in {setting}! Thank you for playing. Goodbye!",
            "sourceText": f"Great job exploring {title} with me today! Thank you for playing. Goodbye!",
        },
    ]
    scenes = _reconcile(scenes, duration)

    return validate_storyline({
        "ageBand": storyline_flow["ageBand"],
        "language": "en-US",
        "targetDurationSeconds": duration,
        "setting": setting,
        "plannedSections": sections,
        "scenes": scenes,
        "sourceInstruction": instruction,
        "generator": "demo-deterministic",
    })


def demo_storyline(instruction: str, age_band: str, duration: int) -> dict[str, Any]:
    flow = demo_storyline_flow(instruction, age_band, duration)
    return demo_script_from_storyline(flow, instruction, duration)


def generate_script_from_storyline(
    storyline_flow: dict[str, Any], instruction: str, settings: Settings
) -> dict[str, Any]:
    validate_storyline_flow(storyline_flow)
    duration = storyline_flow["targetDurationSeconds"]
    age_band = storyline_flow["ageBand"]

    if settings.demo_mode:
        return demo_script_from_storyline(storyline_flow, instruction, duration)

    char = storyline_flow.get("leadCharacter", {})
    char_name = char.get("name", "Pico")
    char_type = char.get("characterType", "robot")
    if char_type not in CHARACTER_TYPES:
        char_type = "robot"
    setting = storyline_flow["setting"]

    system = (
        f"You are a scriptwriter and dialogue writer for child-facing educational videos for ages {age_band}. "
        f"Target total video duration is {duration} seconds. "
        "You are given an APPROVED gamified storyline flow and the researcher's experimental protocol. "
        "From this approved storyline flow ONLY, write the scene-by-scene script and the EXACT spoken dialogues "
        f"(audioScript) spoken by the lead character {char_name} in the video. "
        f"Storyline Flow Title: {storyline_flow.get('title')}\n"
        f"Narrative Premise: {storyline_flow.get('narrativePremise')}\n"
        f"One fixed setting for every scene: {setting}\n"
        f"Gamification Elements: {json.dumps(storyline_flow.get('gamificationElements', {}))}\n"
        f"Flow Steps: {json.dumps(storyline_flow.get('flowSteps', []))}\n\n"
        "Rules:\n"
        f"1. Every scene must feature the lead character '{char_name}' of characterType '{char_type}'.\n"
        f"2. Keep every scene in the exact same physical setting: {setting}. Never move to another location, add a new scenario, or imply travel. "
        "Practice, formal rounds, and closing are continuations of this same scene and activity, not new places or adventures.\n"
        "3. The central activity must remain the researcher's exact experiment task in every scene. The story is only a consistent wrapper; do not replace the task with a different quest.\n"
        "4. Keep the same background and display throughout. Vary only the character's pose and the trial stimuli; do not introduce a new room, landscape, vehicle, island, ocean, or challenge chamber.\n"
        "5. The dialogues in audioScript must directly bring the gamified storyline flow to life in the video while referring to the same place and task.\n"
        "6. Preserve every experimental rule, stimulus exposure time, practice round, and formal trial count.\n"
        "7. For every practice/formal trial, include the trial object: "
        "{ phase: 'practice'|'formal', displayNumbers: int[], missingNumber: int, displayDurationSeconds: float, responseWindowSeconds: float }.\n"
        "8. Use [PAUSE N seconds] inside audioScript for silent stimulus display windows or response time.\n"
        "9. Do not include correctness feedback (e.g. do not say 'you got it right').\n"
        "10. Include a friendly closing scene that thanks the player without changing the setting or activity.\n"
        "Return ONLY one JSON object with a 'scenes' array. Each scene: durationSeconds, characterType, characterName, "
        "characterState, visualAssetTag, setting (must exactly match the fixed setting), audioScript, and optional trial."
    )

    result = call_groq_json(
        system,
        f'Researcher instructions:\n"""\n{instruction}\n"""',
        settings,
        max_tokens=1400,
    )

    raw_scenes = result.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Groq returned no scenes.")

    sections = [
        {
            "sectionOrder": step["stepNumber"],
            "title": step["title"],
            "purpose": step["gamifiedObjective"],
            "durationSeconds": step["durationSeconds"],
            "requiredContent": [step.get("protocolRule", "Preserve experiment protocol.")],
        }
        for step in storyline_flow["flowSteps"]
    ]
    sections = _ensure_closing(_reconcile(sections, duration))

    scenes: list[dict[str, Any]] = []
    trial_counter = 1
    for idx, value in enumerate(raw_scenes, start=1):
        raw = dict(value)
        narration = str(raw.get("audioScript") or "").strip()
        if not narration:
            raise ValueError(f"Scene {idx} has no audioScript.")

        scene: dict[str, Any] = {
            "sceneOrder": idx,
            "durationSeconds": max(0.5, float(raw.get("durationSeconds", 1))),
            "characterType": char_type,
            "characterName": char_name,
            "characterState": str(raw.get("characterState") or "attentive"),
            "visualAssetTag": str(raw.get("visualAssetTag") or f"scene_{idx}"),
            "setting": setting,
            "audioScript": narration,
            "sourceText": narration,
        }

        trial = raw.get("trial")
        if isinstance(trial, dict):
            nums = trial.get("displayNumbers")
            missing = trial.get("missingNumber")
            if isinstance(nums, list) and nums and missing in nums:
                phase = str(trial.get("phase") or "formal").lower()
                if phase not in TRIAL_PHASES:
                    phase = "formal"
                scene["trial"] = {
                    "trialNumber": trial_counter,
                    "phase": phase,
                    "displayNumbers": [int(x) for x in nums],
                    "missingNumber": int(missing),
                    "displayDurationSeconds": max(0.1, float(trial.get("displayDurationSeconds", 2))),
                    "responseWindowSeconds": max(0.1, float(trial.get("responseWindowSeconds", 5))),
                }
                trial_counter += 1
        scenes.append(scene)

    scenes = _reconcile(scenes, duration)

    return validate_storyline({
        "ageBand": age_band,
        "language": "en-US",
        "targetDurationSeconds": duration,
        "setting": setting,
        "plannedSections": sections,
        "scenes": scenes,
        "sourceInstruction": instruction,
        "generator": f"groq:{settings.groq_model}:from-approved-flow",
    })


def generate_storyline(instruction: str, age_band: str, duration: int, settings: Settings) -> dict[str, Any]:
    flow = generate_storyline_flow(instruction, age_band, duration, settings)
    return generate_script_from_storyline(flow, instruction, settings)


class PipelineService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.runs_dir = settings.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_storyline_run(
        self,
        instruction: str,
        age_band: str,
        duration: int,
        target_language: str,
        lead_character: str | None = None,
        setting: str | None = None,
        story_idea: str | None = None,
    ) -> dict[str, Any]:
        flow = generate_storyline_flow(
            instruction,
            age_band,
            duration,
            self.settings,
            lead_character=lead_character,
            setting=setting,
            story_idea=story_idea,
        )
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        timestamp = now_iso()
        self.db.upsert_run({
            "id": run_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "instruction": instruction,
            "age_band": age_band,
            "target_duration_seconds": duration,
            "target_language": target_language,
            "status": "storyline_review_required",
            "approved": False,
            "storyline_flow_approved": False,
            "storyline_flow_json": flow,
            "fps": 30,
        })
        return {"runId": run_id, "storylineFlow": flow, "status": "storyline_review_required"}

    def save_storyline_flow(self, run_id: str, flow: dict[str, Any]) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("storyline_flow_approved"):
            raise ValueError("Storyline flow is approved and locked. Unlock it to make changes.")
        validated = validate_storyline_flow(copy.deepcopy(flow))
        self.db.patch_run(run_id, storyline_flow_json=validated, updated_at=now_iso())
        return validated

    def approve_storyline_flow(self, run_id: str, flow: dict[str, Any] | None = None) -> dict[str, Any]:
        run = self._require_run(run_id)
        if flow is not None:
            validated = validate_storyline_flow(copy.deepcopy(flow))
        else:
            validated = run.get("storyline_flow_json")
            if not validated:
                raise ValueError("No storyline flow found to approve.")
        self.db.patch_run(
            run_id,
            storyline_flow_json=validated,
            storyline_flow_approved=True,
            status="storyline_approved",
            updated_at=now_iso(),
        )
        return {
            "runId": run_id,
            "storylineFlow": validated,
            "storylineFlowApproved": True,
            "status": "storyline_approved",
        }

    def unlock_storyline_flow(self, run_id: str) -> dict[str, Any]:
        self._require_run(run_id)
        self.db.patch_run(
            run_id,
            storyline_flow_approved=False,
            approved=False,
            status="storyline_review_required",
            updated_at=now_iso(),
        )
        return {"runId": run_id, "storylineFlowApproved": False, "status": "storyline_review_required"}

    def generate_script(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if not run.get("storyline_flow_approved"):
            raise ValueError(
                "Storyline flow must be approved by the researcher before generating the script and dialogues."
            )
        flow = run.get("storyline_flow_json")
        if not flow:
            raise ValueError("Run has no approved storyline flow.")
        script = generate_script_from_storyline(flow, run["instruction"], self.settings)
        self.db.patch_run(
            run_id,
            english_storyline_json=script,
            approved=False,
            status="script_review_required",
            updated_at=now_iso(),
        )
        self.db.replace_scenes(run_id, script["scenes"])
        return {"runId": run_id, "storyline": script, "status": "script_review_required"}

    def create_run(
        self,
        instruction: str,
        age_band: str,
        duration: int,
        target_language: str,
        lead_character: str | None = None,
        setting: str | None = None,
        story_idea: str | None = None,
    ) -> dict[str, Any]:
        # Backwards compatible full generation
        flow = generate_storyline_flow(
            instruction,
            age_band,
            duration,
            self.settings,
            lead_character=lead_character,
            setting=setting,
            story_idea=story_idea,
        )
        storyline = generate_script_from_storyline(flow, instruction, self.settings)
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        timestamp = now_iso()
        self.db.upsert_run({
            "id": run_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "instruction": instruction,
            "age_band": age_band,
            "target_duration_seconds": duration,
            "target_language": target_language,
            "status": "review_required",
            "approved": False,
            "storyline_flow_approved": True,
            "storyline_flow_json": flow,
            "fps": 30,
            "english_storyline_json": storyline,
        })
        self.db.replace_scenes(run_id, storyline["scenes"])
        return {
            "runId": run_id,
            "storylineFlow": flow,
            "storyline": storyline,
            "status": "review_required",
        }

    def save_storyline(self, run_id: str, storyline: dict[str, Any]) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run["approved"]:
            raise ValueError("Script is approved and locked. Unlock the script to edit.")
        validated = validate_storyline(copy.deepcopy(storyline))
        self.db.patch_run(run_id, english_storyline_json=validated, updated_at=now_iso())
        self.db.replace_scenes(run_id, validated["scenes"])
        return validated

    def approve(self, run_id: str, storyline: dict[str, Any] | None = None) -> dict[str, Any]:
        run = self._require_run(run_id)
        if not run.get("storyline_flow_approved"):
            raise ValueError("Storyline flow must be approved before script approval.")
        if storyline is not None:
            validated = validate_storyline(copy.deepcopy(storyline))
            self.db.patch_run(run_id, english_storyline_json=validated)
            self.db.replace_scenes(run_id, validated["scenes"])
        else:
            validated = run.get("english_storyline_json")
            if not validated:
                raise ValueError("No script found to approve.")
        self.db.patch_run(run_id, approved=True, status="approved", updated_at=now_iso())
        return {"runId": run_id, "approved": True, "storyline": validated}

    def unlock_script(self, run_id: str) -> dict[str, Any]:
        self._require_run(run_id)
        self.db.patch_run(run_id, approved=False, status="script_review_required", updated_at=now_iso())
        return {"runId": run_id, "approved": False, "status": "script_review_required"}

    def translate(self, run_id: str, target_language: str, provider: str = "sarvam") -> dict[str, Any]:
        run = self._require_run(run_id)
        if not run["approved"]:
            raise ValueError("Researcher approval of the script is required before translation.")
        if provider not in {"sarvam", "bhashini"}:
            raise ValueError("translation provider must be 'sarvam' or 'bhashini'.")

        storyline = run["english_storyline_json"]
        translated = copy.deepcopy(storyline)
        translated["language"] = target_language
        translated["translationProvider"] = provider

        translator = translate_text_sarvam if provider == "sarvam" else translate_text_bhashini
        for scene in translated["scenes"]:
            scene["translatedText"] = translator(scene["audioScript"], target_language, self.settings)
            scene["translationProvider"] = provider

        self.db.patch_run(
            run_id,
            target_language=target_language,
            translated_storyline_json=translated,
            status="translated",
            updated_at=now_iso(),
        )
        self.db.replace_scenes(run_id, translated["scenes"])
        return {
            "runId": run_id,
            "storyline": translated,
            "status": "translated",
            "translationProvider": provider,
        }

    def voiceover(self, run_id: str, provider: str, voice: str, fps: int) -> dict[str, Any]:
        run = self._require_run(run_id)
        if not run["approved"]:
            raise ValueError("Researcher approval is required before voiceover.")
        translated = run.get("translated_storyline_json")
        if not translated:
            raise ValueError("Translate the approved script before voiceover.")
        if fps not in {24, 25, 30, 50, 60}:
            raise ValueError("fps must be one of 24, 25, 30, 50, 60.")

        audio_dir = self.runs_dir / run_id / "audio" / provider
        audio_dir.mkdir(parents=True, exist_ok=True)
        scene_results: list[dict[str, Any]] = []
        wav_chunks: list[bytes] = []
        cursor_ms = 0
        cursor_frame = 0
        lang = translated["language"]
        for scene in translated["scenes"]:
            order = int(scene["sceneOrder"])
            text = str(scene.get("translatedText") or scene.get("audioScript") or "").strip()
            if not text:
                raise ValueError(f"Scene {order} has no text for TTS.")
            wav = synthesize(provider, text, lang, voice, self.settings)
            filename = f"scene_{order:03d}_{lang.split('-')[0]}_{provider}.wav"
            path = audio_dir / filename
            path.write_bytes(wav)
            duration_ms = wav_duration_ms(path)
            start_time_ms = cursor_ms
            end_time_ms = start_time_ms + duration_ms
            start_frame = cursor_frame
            total_frames = max(1, round(duration_ms * fps / 1000))
            end_frame = start_frame + total_frames
            enriched = copy.deepcopy(scene)
            enriched.update({
                "slideNumber": order,
                "slideId": f"slide-{order:03d}",
                "ttsProvider": provider,
                "voice": voice,
                "language": lang,
                "audioFileName": filename,
                "audioUrl": f"/api/runs/{run_id}/audio/{provider}/{filename}",
                "audioDurationMs": duration_ms,
                "startTimeMs": start_time_ms,
                "endTimeMs": end_time_ms,
                "startTimeSeconds": round(start_time_ms / 1000, 3),
                "endTimeSeconds": round(end_time_ms / 1000, 3),
                "timelineStartMs": start_time_ms,
                "timelineEndMs": end_time_ms,
                "startFrame": start_frame,
                "totalFrames": total_frames,
                "endFrameExclusive": end_frame,
                "fps": fps,
            })
            scene_results.append(enriched)
            wav_chunks.append(wav)
            cursor_ms = end_time_ms
            cursor_frame = end_frame

        combined = concatenate_wavs(wav_chunks)
        combined_name = f"combined_{lang.split('-')[0]}_{provider}.wav"
        combined_path = audio_dir / combined_name
        combined_path.write_bytes(combined)
        combined_ms = wav_duration_ms(combined_path)
        dataset = {
            "datasetVersion": "1.0",
            "runId": run_id,
            "generatedAt": now_iso(),
            "ageBand": translated["ageBand"],
            "language": lang,
            "targetDurationSeconds": translated["targetDurationSeconds"],
            "approvedByResearcher": True,
            "translationProvider": translated.get("translationProvider", "sarvam"),
            "ttsProvider": provider,
            "voice": voice,
            "fps": fps,
            "sceneCount": len(scene_results),
            "audioTimelineDurationMs": cursor_ms,
            "combinedAudioDurationMs": combined_ms,
            "combinedAudioFileName": combined_name,
            "combinedAudioUrl": f"/api/runs/{run_id}/audio/{provider}/{combined_name}",
            "plannedSections": translated["plannedSections"],
            "scenes": scene_results,
        }
        dataset_path = self.runs_dir / run_id / f"dataset_{provider}.json"
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
        self.db.patch_run(
            run_id,
            dataset_json=dataset,
            combined_audio_file=str(combined_path),
            tts_provider=provider,
            voice=voice,
            fps=fps,
            status="voiceover_complete",
            updated_at=now_iso(),
        )
        self.db.replace_scenes(run_id, scene_results)
        return dataset

    def get_run_public(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        return {
            "id": run["id"],
            "createdAt": run["created_at"],
            "updatedAt": run["updated_at"],
            "instruction": run["instruction"],
            "ageBand": run["age_band"],
            "targetDurationSeconds": run["target_duration_seconds"],
            "targetLanguage": run["target_language"],
            "status": run["status"],
            "storylineFlowApproved": bool(run.get("storyline_flow_approved")),
            "storylineFlow": run.get("storyline_flow_json"),
            "approved": bool(run.get("approved")),
            "storyline": run.get("english_storyline_json"),
            "ttsProvider": run["tts_provider"],
            "voice": run["voice"],
            "fps": run["fps"],
            "translatedStoryline": run.get("translated_storyline_json"),
            "dataset": run.get("dataset_json"),
        }

    def audio_path(self, run_id: str, provider: str, filename: str) -> Path:
        if provider not in {"azure", "sarvam"}:
            raise ValueError("Invalid provider.")
        if Path(filename).name != filename or not re.fullmatch(r"[A-Za-z0-9_.-]+\.wav", filename):
            raise ValueError("Invalid audio filename.")
        path = (self.runs_dir / run_id / "audio" / provider / filename).resolve()
        expected = (self.runs_dir / run_id / "audio" / provider).resolve()
        if expected not in path.parents or not path.exists():
            raise FileNotFoundError(filename)
        return path

    def _require_run(self, run_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"run-[a-f0-9]{12}", run_id):
            raise ValueError("Invalid run ID.")
        run = self.db.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run
