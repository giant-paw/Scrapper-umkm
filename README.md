Membuat exe :

1. cek apakah sudah terinstal pyinstaller : 
  'pip install pyinstaller'

2. Jalankan perintah compile / build :
  'pyinstaller --noconfirm --onedir --windowed --collect-all customtkinter --collect-all playwright app.py'

3. Pindahkan File GeoJSON
     -Buka folder proyek Anda.
   - Salin/Copy file idsls fix.geojson.
   - Buka folder dist -> buka folder app.
   - Paste file idsls fix.geojson tersebut di dalam folder app, sejajar dengan file app.exe
  
4. Zip folder App
