/** Plain-English labels for beginners (timeline + media bin + preview). */

const TRANSITION: Record<string, string> = {
  jigsaw: "Puzzle cut",
  whip_pan: "Hard cut",
  push: "Push zoom",
  pop_slam: "Pop slam",
  flash_white: "White flash",
  hard_cut: "Hard cut",
  zoom_in: "Zoom in",
  zoom_out: "Zoom out",
  zigzag: "Zigzag",
  spin: "Spin",
};

const RECIPE: Record<string, string> = {
  clean: "Clean hit",
  slow: "Slow-mo",
  punch: "Punch zoom",
  cinematic: "Cinematic",
};

const HIT: Record<string, string> = {
  glow: "Glow flash",
  flash_blur: "Flash blur",
  flash_shake: "Flash shake",
  impact: "Impact",
  none: "No hit FX",
};

export function transitionLabel(type: string | undefined | null): string {
  if (!type) return "Hard cut";
  return TRANSITION[type] || type.replace(/_/g, " ");
}

export function recipeLabel(recipe: string | undefined | null): string {
  if (!recipe) return "Clean hit";
  return RECIPE[recipe] || recipe;
}

export function hitLabel(style: string | undefined | null): string {
  if (!style) return "Flash blur";
  return HIT[style] || style.replace(/_/g, " ");
}

export function effectLabel(raw: string): string {
  if (raw.startsWith("recipe:")) return recipeLabel(raw.slice(7));
  if (raw === "ghost" || raw === "ghost_freeze") return "Ghost freeze";
  if (raw === "gun_outline" || raw === "gun") return "Weapon glow";
  if (raw === "kill" || raw.startsWith("Kill")) return "Kill hit";
  return transitionLabel(raw) || raw.replace(/_/g, " ");
}
