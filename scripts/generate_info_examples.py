from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W,H=1024,500
out=Path('images/banners')
out.mkdir(parents=True, exist_ok=True)
font_path='assets/fonts/NotoSans-Regular.ttf'
font_bold=font_path

def font(size): return ImageFont.truetype(font_bold,size)
def make(name, bg, accent, title, subtitle, icon):
    im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
    for y in range(H):
        t=y/H; c=tuple(int(bg[i]*(1-t*.45)+accent[i]*t*.18) for i in range(3))
        d.line((0,y,W,y),fill=c)
    d.rounded_rectangle((34,34,390,466),radius=28,fill=(18,22,34),outline=accent,width=4)
    d.ellipse((90,78,334,322),fill=accent,outline=(255,255,255),width=5)
    d.text((212,200),icon,anchor='mm',font=font(112),fill=(18,22,34))
    d.text((55,360),'FISSURE BOT',font=font(30),fill=accent)
    d.text((55,404),'Справка и патчи',font=font(22),fill=(230,235,245))
    d.text((450,120),title,font=font(48),fill=(245,247,255))
    d.text((450,205),subtitle,font=font(25),fill=(180,190,215))
    d.rounded_rectangle((450,285,920,395),radius=22,fill=(25,30,48),outline=accent,width=3)
    d.text((685,340),'/info  →  PATCH-FISSURE',anchor='mm',font=font(26),fill=(245,247,255))
    im.save(out/f'{name}.webp','WEBP',quality=92)

make('info_option_dark',(8,11,20),(255,140,66),'Информация','Команды, правила и обновления','i')
make('info_option_blue',(7,18,34),(75,170,255),'Информация','Команды, правила и обновления','i')
make('info_option_purple',(18,9,32),(170,100,255),'Информация','Команды, правила и обновления','i')
print('generated', [p.name for p in out.glob('info_option_*.webp')])