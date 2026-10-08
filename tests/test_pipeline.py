from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.db import Database
from app.pipeline import (
    PipelineService,
    demo_storyline,
    demo_storyline_flow,
    generate_script_from_storyline,
    validate_storyline,
)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(
            data_dir=root,
            demo_mode=True,
            groq_api_key="",
            groq_model="demo",
            groq_max_tokens=1000,
            sarvam_api_key="",
            bhashini_user_id="",
            bhashini_api_key="",
            bhashini_pipeline_id="64392f96daac500b55c543cd",
            bhashini_ulca_config_endpoint="https://example.invalid/config",
            bhashini_inference_url="https://example.invalid/inference",
            azure_speech_key="",
            azure_speech_region="centralindia",
        )
        self.db = Database(root / "balvibe.db")
        self.service = PipelineService(self.settings, self.db)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_storyline_generation_and_validation(self) -> None:
        story = demo_storyline("Show six numbers and hide one.", "6-8", 120)
        self.assertEqual(story["ageBand"], "6-8")
        self.assertAlmostEqual(sum(scene["durationSeconds"] for scene in story["scenes"]), 120)
        self.assertEqual(len({scene["characterName"] for scene in story["scenes"]}), 1)
        self.assertTrue(story["setting"])
        self.assertEqual({scene["setting"] for scene in story["scenes"]}, {story["setting"]})
        story["scenes"][1]["setting"] = "open ocean"
        self.assertEqual(
            {scene["setting"] for scene in validate_storyline(story)["scenes"]},
            {story["setting"]},
        )

    def test_generated_script_keeps_one_setting_and_experiment_task(self) -> None:
        instruction = "Show six numbers and ask which number disappeared."
        flow = demo_storyline_flow(instruction, "6-8", 90, setting="a small island beach")
        flow["flowSteps"][1]["setting"] = "open ocean"
        live_settings = replace(self.settings, demo_mode=False, groq_api_key="test-key")

        with patch(
            "app.pipeline.call_groq_json",
            return_value={
                "scenes": [
                    {
                        "durationSeconds": 90,
                        "characterState": "attentive",
                        "visualAssetTag": "number_display",
                        "setting": "open ocean",
                        "audioScript": "Look at the numbers and tell me which one disappeared.",
                    }
                ]
            },
        ) as groq:
            storyline = generate_script_from_storyline(flow, instruction, live_settings)

        prompt = groq.call_args.args[0]
        self.assertIn("same physical setting", prompt)
        self.assertIn("same scene and activity", prompt)
        self.assertEqual(storyline["setting"], "a small island beach")
        self.assertEqual(storyline["scenes"][0]["setting"], "a small island beach")

    def test_approval_translation_and_both_tts_contracts(self) -> None:
        created = self.service.create_run(
            "Show six numbers for two seconds, hide one, and ask which number disappeared.",
            "6-8",
            120,
            "hi-IN",
        )
        run_id = created["runId"]
        self.service.approve(run_id, created["storyline"])
        translated = self.service.translate(run_id, "hi-IN")
        self.assertTrue(all("translatedText" in s for s in translated["storyline"]["scenes"]))

        azure = self.service.voiceover(run_id, "azure", "hi-IN-SwaraNeural", 30)
        self._assert_contract(azure, "azure")
        sarvam = self.service.voiceover(run_id, "sarvam", "ritu", 24)
        self._assert_contract(sarvam, "sarvam")

        saved = self.db.get_run(run_id)
        self.assertEqual(saved["status"], "voiceover_complete")
        self.assertEqual(saved["tts_provider"], "sarvam")
        self.assertTrue((self.settings.data_dir / "runs" / run_id / "audio" / "azure").exists())
        self.assertTrue((self.settings.data_dir / "runs" / run_id / "audio" / "sarvam").exists())

    def test_bhashini_translation_provider_contract(self) -> None:
        created = self.service.create_run(
            "Show six numbers for two seconds, hide one, and ask which number disappeared.",
            "6-8",
            120,
            "hi-IN",
        )
        run_id = created["runId"]
        self.service.approve(run_id, created["storyline"])
        translated = self.service.translate(run_id, "hi-IN", "bhashini")
        self.assertEqual(translated["translationProvider"], "bhashini")
        self.assertEqual(translated["storyline"]["translationProvider"], "bhashini")
        self.assertTrue(all(
            scene.get("translationProvider") == "bhashini"
            and "translatedText" in scene
            for scene in translated["storyline"]["scenes"]
        ))

    def test_storyline_flow_stage_and_approval_gate(self) -> None:
        # 1. Create storyline run
        created = self.service.create_storyline_run(
            "Show six numbers for two seconds, hide one, and ask which number disappeared.",
            "6-8",
            120,
            "hi-IN",
        )
        run_id = created["runId"]
        flow = created["storylineFlow"]
        self.assertEqual(flow["ageBand"], "6-8")
        self.assertIn("gamificationElements", flow)
        self.assertIn("leadCharacter", flow)
        self.assertIn("flowSteps", flow)
        self.assertAlmostEqual(sum(s["durationSeconds"] for s in flow["flowSteps"]), 120)
        self.assertEqual({step["setting"] for step in flow["flowSteps"]}, {flow["setting"]})

        # 2. Verify script generation is blocked BEFORE storyline approval
        with self.assertRaises(ValueError) as cm:
            self.service.generate_script(run_id)
        self.assertIn("Storyline flow must be approved", str(cm.exception))

        # 3. Approve storyline flow
        approved_flow = self.service.approve_storyline_flow(run_id, flow)
        self.assertTrue(approved_flow["storylineFlowApproved"])
        self.assertEqual(approved_flow["status"], "storyline_approved")

        # 4. Generate script from approved storyline flow
        script_res = self.service.generate_script(run_id)
        script = script_res["storyline"]
        self.assertEqual(script_res["status"], "script_review_required")
        self.assertGreater(len(script["scenes"]), 0)
        # Verify dialogues reference character
        char_name = flow["leadCharacter"]["name"]
        self.assertTrue(all(s["characterName"] == char_name for s in script["scenes"]))
        self.assertEqual({scene["setting"] for scene in script["scenes"]}, {flow["setting"]})
        self.assertNotIn("challenge chamber", " ".join(scene["audioScript"] for scene in script["scenes"]).lower())

        # 5. Verify translation is blocked BEFORE script approval
        with self.assertRaises(ValueError) as cm:
            self.service.translate(run_id, "hi-IN")
        self.assertIn("approval", str(cm.exception).lower())

        # 6. Approve script and translate
        self.service.approve(run_id, script)
        trans = self.service.translate(run_id, "hi-IN")
        self.assertEqual(trans["status"], "translated")

    def test_custom_story_direction_and_character_choice(self) -> None:
        created = self.service.create_storyline_run(
            "Show six numbers for two seconds, hide one, and ask which number disappeared.",
            "6-8",
            90,
            "hi-IN",
            lead_character="Mira the moon rabbit",
            setting="lantern lit forest",
            story_idea="help find the missing flowers",
        )
        flow = created["storylineFlow"]
        self.assertIn("Mira", flow["leadCharacter"]["name"])
        self.assertEqual(flow["leadCharacter"]["characterType"], "animal")
        self.assertIn("lantern lit forest", flow["setting"])
        self.assertIn("flower", flow["narrativePremise"].lower())

        # Test user can edit character before approving
        flow["leadCharacter"]["name"] = "Mira"
        saved = self.service.save_storyline_flow(created["runId"], flow)
        self.assertEqual(saved["leadCharacter"]["name"], "Mira")

        self.service.approve_storyline_flow(created["runId"], saved)
        script_res = self.service.generate_script(created["runId"])
        script = script_res["storyline"]
        self.assertTrue(all(s["characterName"] == "Mira" for s in script["scenes"]))

    def _assert_contract(self, dataset: dict, provider: str) -> None:
        self.assertEqual(dataset["ttsProvider"], provider)
        self.assertGreater(dataset["sceneCount"], 0)
        self.assertGreater(dataset["combinedAudioDurationMs"], 0)
        last_end = 0
        last_frame = 0
        for scene in dataset["scenes"]:
            for key in (
                "audioFileName", "audioDurationMs", "startTimeMs", "endTimeMs",
                "timelineStartMs", "timelineEndMs", "startFrame", "totalFrames",
                "endFrameExclusive", "fps", "ttsProvider", "voice", "visualAssetTag",
                "slideNumber", "slideId", "startTimeSeconds", "endTimeSeconds",
            ):
                self.assertIn(key, scene)
            self.assertEqual(scene["startTimeMs"], last_end)
            self.assertEqual(scene["startFrame"], last_frame)
            self.assertGreater(scene["audioDurationMs"], 0)
            last_end = scene["endTimeMs"]
            last_frame = scene["endFrameExclusive"]
        self.assertEqual(dataset["audioTimelineDurationMs"], last_end)


if __name__ == "__main__":
    unittest.main()
