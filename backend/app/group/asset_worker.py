"""Minimal spawn target: no service, catalogue or application imports."""
import io

def decode_worker(raw,pipe):
 try:
  from PIL import Image,ImageOps
  Image.MAX_IMAGE_PIXELS=16_000_000
  import warnings
  warnings.simplefilter('error',Image.DecompressionBombWarning)
  with Image.open(io.BytesIO(raw)) as image:
   if image.format not in ('PNG','JPEG','WEBP'):raise ValueError('Use PNG, JPEG or WebP; SVG is not accepted')
   if image.width*image.height>16_000_000 or image.width<1 or image.height<1:raise ValueError('Image dimensions exceed limit')
   if getattr(image,'n_frames',1)!=1:raise ValueError('Animated images are not accepted')
   image.load();image=ImageOps.exif_transpose(image).convert('RGBA');variants={}
   for size in (512,1024,2048):
    resized=image.copy();resized.thumbnail((size,size),Image.Resampling.LANCZOS);out=io.BytesIO();resized.save(out,format='PNG');variants[str(size)]=out.getvalue()
   pipe.send({'variants':variants,'width':image.width,'height':image.height})
 except Exception as e:pipe.send({'error':str(e)[:200]})
 finally:pipe.close()

