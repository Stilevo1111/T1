import subprocess, os

repo = r"D:\fissure-bot\Seredin999\fissure-bot_new"
outdir = r"C:\Users\akado\AppData\Local\Temp\kilo\diffs"
os.makedirs(outdir, exist_ok=True)

files = [
    ("obs_widget.py", "755b712"),
    ("roll_balancer.py", "0a06a18"),
    ("roll_balancer.py", "54679b4"),
    ("techies.py", "0a06a18"),
    ("techies.py", "6999236"),
    ("techies.py", "f34c1f3"),
    ("techies.py", "22ba76d"),
    ("techies.py", "0cc58e3"),
    ("techies.py", "2a781a0"),
    ("cache_service.py", "755b712"),
    ("cache_service.py", "0ad5e8c"),
    ("fissure.py", "6999236"),
    ("fissure.py", "f34c1f3"),
    ("fissure.py", "c7b2c04"),
    ("config.py", "de23686"),
    ("config.py", "24277eb"),
    ("bot_utils.py", "1fbbb01"),
    ("bot_utils.py", "11ef2d8"),
    ("bot_utils.py", "b75570d"),
    ("bot_utils.py", "e58644c"),
    ("bot_utils.py", "f7bb0bc"),
    ("bot_utils.py", "36ff42f"),
    ("bot_utils.py", "aa8a00c"),
    ("bot_utils.py", "6999236"),
    ("database.py", "1fbbb01"),
    ("database.py", "11ef2d8"),
    ("database.py", "6999236"),
    ("database.py", "755b712"),
    ("database.py", "b902c57"),
    ("database.py", "f0ca427"),
    ("database.py", "3c9c718"),
    ("database.py", "4a2f5dd"),
    ("database.py", "34807b5"),
    ("digest.py", "1fbbb01"),
    ("digest.py", "11ef2d8"),
    ("digest.py", "e903799"),
    ("digest.py", "4dc4f71"),
    ("digest.py", "ca79f0e"),
    ("digest.py", "6999236"),
    ("digest.py", "755b712"),
    ("digest.py", "0ad5e8c"),
    ("digest.py", "54fbe37"),
    ("digest.py", "08d6368"),
    ("digest.py", "50e8f0d"),
    ("digest.py", "94985cb"),
    ("digest.py", "1a7dc81"),
    ("digest.py", "2757997"),
    ("digest.py", "5a13efc"),
    ("digest.py", "1ef04f5"),
    ("digest.py", "14827ea"),
    ("mute.py", "2757997"),
    ("mute.py", "24277eb"),
    ("mute.py", "304b0ce"),
    ("mute.py", "4be3679"),
    ("mute.py", "bd119c0"),
    ("mute.py", "11ef2d8"),
    ("mute.py", "1fbbb01"),
]

for fname, h in files:
    r = subprocess.run(["git", "show", h, "--", fname], cwd=repo,
                       capture_output=True, text=True)
    safe = fname.replace(".", "_")
    outpath = os.path.join(outdir, safe + "_" + h + ".txt")
    with open(outpath, "w") as f:
        f.write(r.stdout)
    print(outpath)