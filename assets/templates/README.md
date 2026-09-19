## Kill-feed templates

The default highlight detector uses OpenCV template matching inside the Valorant kill-feed HUD region.

Place these PNG files in this folder (names are important):

- `kill_skull.png`
- `headshot_skull.png`
- `death_skull.png`
- `assist_icon.png`

### How to capture good templates

- Use a **lossless screenshot** from your own footage (avoid JPEG).
- Capture the **smallest tight bounding box** around the icon (no extra padding).
- Keep the icon **exactly as it appears** (same UI scale, same resolution if possible).
- Prefer PNG with an **alpha channel** (transparency). The detector will automatically use alpha as a mask.

### Testing

If templates are missing, the kill-feed detector will return **no events** (and the system will fall back to audio peaks).
