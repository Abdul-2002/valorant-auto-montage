# Raw dataset sources (for re-annotation)

## Local VODs (E:\VALORANT)

308 DVR/mp4 files (~141 GB) live on `E:\VALORANT`. Annotation workspace:

- `E:\VALORANT\_training_raw\` — copy of Roboflow/public raw packs + extracted stills
- `E:\VALORANT\_training_raw\vod_frames\` — 1 frame / 2s from each VOD (**done**: 306/308 ok, ~18.3k JPEGs; 1 tiny + 1 empty skipped)

```powershell
py -3.12 training/scripts/extract_vod_frames.py
```

## Already downloaded (no API key)

| Slug | Source | ~Images | Notes |
|---|---|---:|---|
| `leaf48_yolo_valorant_v3` | [Leaf48 dataset-v3.0](https://github.com/Leaf48/YOLO-Models-For-Valorant/releases/tag/dataset-v3.0) | 9.2k | Public zip; agent/world labels — re-annotate |

```powershell
python training/scripts/download_public_zips.py
```

## Roboflow Universe (needs `ROBOFLOW_API_KEY`)

```powershell
$env:ROBOFLOW_API_KEY = "rf_..."   # or put ROBOFLOW_API_KEY= in .env
# Use Python 3.12+ with wheels (3.15 may fail building deps on Windows)
py -3.12 -m pip install roboflow
py -3.12 training/scripts/download_roboflow_raw.py
```

Do **not** merge these into `valorant_kill_banner` until you re-label to the 10-class taxonomy in `training/data.yaml`.

Approximate public image counts (Universe; versions may differ after download):

| Slug | Roboflow | ~Images | Original classes (approx) | Role |
|---|---|---:|---|---|
| `valorant_kill_banner` | suman-kumar-dx18l/valorant-kill-banner-woebs v1 | 1.4k | kill-1…6, round-*, spectating, spike-plant | Primary HUD |
| `detect_kill_banner_zuu0v` | detect-qa7ry/valorant-kill-banner-zuu0v v1 | 338 | kill banner | HUD |
| `valorant_spectating` | suman-kumar-dx18l/valorant-spectating v1 | 200 | kill-*, spectating, round-end, spike-plant | Spectator / death UI |
| `simple_valorant_ui` | christalin-dorsey-ljvjf/simple-valorant-ui-detector v1 | 1.7k | kill-1…6, round-*, spectating, spike-plant | HUD duplicate taxonomy |
| `kill_banner_detection_alwsr` | valorant-kill-banner-detection/...-alwsr v3 | 80–180 | kill_banner | Banner-only |
| `kill_feed_detector_v4` | clipmaker/valorant-kill-feed-detector-vsayu v4 | 1.7k | killfeed + buy/spectator | Hard negatives |
| `valorant_killfeed_39` | valorant-killfeed/valorant-killfeed v3 | 39 | kill, objects | Tiny killfeed |
| `kasaden_valorant_test` | kasaden/valorant-test-tz2g5-zu96f v10 | 8.5k | killfeed_* + agents/spike | Large mixed |
| `valorant_kills_llb5g` | valorantkills/valorant-kills-llb5g v9 | 1.5k | death/kill/enemy/teammate | Mixed UI+world |
| `yolo_all_death_kills` | valorant-wwdj4/yolo-all-av4di v1 | 584 | death, defuse, kills | Death / kill UI |
| `daniels_valorant_9ufcp` | daniels-magonis-0pjzx/valorant-9ufcp v3 | 9.9k | enemy/teammate/spike | World agents |
| `people_valorant` | matthew-watkins-hugkx/people-valorant v1 | 9k | enemy/teammate/spike | World agents |
| `ai_valorant_9lnsh` | ai-evhra/valorant-9lnsh v3 | 5–16k | person/enemy/game | Volume dump |
| `arif_valorant_kns89` | arif-kobel-dzirq/valorant-kns89 v1 | 2.6k | enemy / enemy_head | Bodies |
| `kota3` | tim-olson-rvtpl/kota3 v3 | — | enemy, teammate, smokes | World |
| `custom_model_3` | om-kulkarni-1f0wf/custom-model-3 v1 | — | Enemy, Friendly, Spike | World / spike |
| `b8t19_enemy` | rishabh-miniclip-gkn5v/-b8t19 v1 | — | enemy | Bodies |
| `wesh_valorant_enemies` | wesh/valorant-jsq9e v1 | 264 | Enemies | Bodies |

Class mismatch is expected. Treat original labels as **hints only**.
