// Local mirror of formations (kept identical to backend match_engine.py).
export const FORMATIONS = {
  "4-3-3": [
    { id: "GK",  pos: "GK",  x: 50, y: 92 },
    { id: "LB",  pos: "LB",  x: 12, y: 72 },
    { id: "CB1", pos: "CB",  x: 36, y: 78 },
    { id: "CB2", pos: "CB",  x: 64, y: 78 },
    { id: "RB",  pos: "RB",  x: 88, y: 72 },
    { id: "CM1", pos: "CM",  x: 28, y: 52 },
    { id: "CAM", pos: "CAM", x: 50, y: 40 },
    { id: "CM2", pos: "CM",  x: 72, y: 52 },
    { id: "LW",  pos: "LW",  x: 15, y: 22 },
    { id: "ST",  pos: "ST",  x: 50, y: 14 },
    { id: "RW",  pos: "RW",  x: 85, y: 22 },
  ],
  "4-4-2": [
    { id: "GK",  pos: "GK",  x: 50, y: 92 },
    { id: "LB",  pos: "LB",  x: 12, y: 72 },
    { id: "CB1", pos: "CB",  x: 36, y: 78 },
    { id: "CB2", pos: "CB",  x: 64, y: 78 },
    { id: "RB",  pos: "RB",  x: 88, y: 72 },
    { id: "LM",  pos: "LM",  x: 14, y: 46 },
    { id: "CM1", pos: "CM",  x: 36, y: 50 },
    { id: "CM2", pos: "CM",  x: 64, y: 50 },
    { id: "RM",  pos: "RM",  x: 86, y: 46 },
    { id: "ST1", pos: "ST",  x: 36, y: 18 },
    { id: "ST2", pos: "ST",  x: 64, y: 18 },
  ],
  "3-5-2": [
    { id: "GK",  pos: "GK",  x: 50, y: 92 },
    { id: "CB1", pos: "CB",  x: 22, y: 78 },
    { id: "CB2", pos: "CB",  x: 50, y: 80 },
    { id: "CB3", pos: "CB",  x: 78, y: 78 },
    { id: "LM",  pos: "LM",  x: 10, y: 50 },
    { id: "CM1", pos: "CM",  x: 32, y: 55 },
    { id: "CAM", pos: "CAM", x: 50, y: 40 },
    { id: "CM2", pos: "CM",  x: 68, y: 55 },
    { id: "RM",  pos: "RM",  x: 90, y: 50 },
    { id: "ST1", pos: "ST",  x: 36, y: 16 },
    { id: "ST2", pos: "ST",  x: 64, y: 16 },
  ],
  "4-2-3-1": [
    { id: "GK",   pos: "GK",   x: 50, y: 92 },
    { id: "LB",   pos: "LB",   x: 12, y: 72 },
    { id: "CB1",  pos: "CB",   x: 36, y: 78 },
    { id: "CB2",  pos: "CB",   x: 64, y: 78 },
    { id: "RB",   pos: "RB",   x: 88, y: 72 },
    { id: "CDM1", pos: "CDM",  x: 36, y: 58 },
    { id: "CDM2", pos: "CDM",  x: 64, y: 58 },
    { id: "CAM",  pos: "CAM",  x: 50, y: 36 },
    { id: "LW",   pos: "LW",   x: 14, y: 28 },
    { id: "RW",   pos: "RW",   x: 86, y: 28 },
    { id: "ST",   pos: "ST",   x: 50, y: 12 },
  ],
};

export const FORMATION_KEYS = Object.keys(FORMATIONS);

export const ovrTint = (ovr) => {
  if (ovr === undefined || ovr === null) return "ovr-50";
  if (ovr >= 93) return "ovr-99";
  if (ovr >= 85) return "ovr-90";
  if (ovr >= 75) return "ovr-80";
  if (ovr >= 65) return "ovr-70";
  return "ovr-50";
};
