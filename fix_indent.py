def fix_profile_card():
    lines = open('dota_mmr.py', 'r', encoding='utf-8').readlines()
    for i, l in enumerate(lines):
        if 'img.alpha_composite(icon' in l:
            lines[i] = '                    img.paste(icon, (tile_x, tile_y), icon)\n'
            print(f'Fixed line {i+1}')
        if 'format="JPEG"' in l and i > 3200:
            lines[i] = '        img.save(buf, format="PNG", optimize=True)\n'
            print(f'Fixed save line {i+1}')
    open('dota_mmr.py', 'w', encoding='utf-8').writelines(lines)

if __name__ == '__main__':
    fix_profile_card()
