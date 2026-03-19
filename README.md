Update 2.5 :
1.  Import Excel File  (Keywoard) 
2.  Fixing Bug maps_place_name excel
3.  Bar progress persentase scrapping
4.  spesifik 'yogyakarta' di pencarian maps. contoh {nama toko} + 'yogyakarta'. untuk fokus pencarian toko di Yogyakarta bukan cabang lain provinsi
5.  Kasus unik Blibli ( Sudah Diperbaiki ), jika barang yang dicari tidak ada di bantul. sebelum diperbaiki, filter lokasi nya tidak ada pilihan 'bantul', tapi aplikasi akan tetap scrapping. Contoh: coba cari 'nitendo', 'dvr' atau 'pabx' di Blibli.com dan ketik filter lokasi 'Bantul', maka tidak ada pilihan 'Bantul' karena tidak ada penjual (toko) disitu. jadi aplikasi dibuat langsung stop tidak melanjutkan scrapping (karena tidak ada toko di Bantul)
6.  fixing minor bug
7.  tampilan waktu lama scrapping
8.  Excel Tersimpan di folder 'data'

*Note : masih banyak kecampur data tampil di platform online shop kabupaten Bantul dan kabupaten lain (Sleman). jadi di excel masih ada banyak diluar ring

<img width="1133" height="857" alt="Screenshot 2026-03-19 104730" src="https://github.com/user-attachments/assets/d10aa3fe-02f7-40ff-8214-96087e08bf33" />

<img width="1130" height="852" alt="image" src="https://github.com/user-attachments/assets/6d230fe3-da75-402a-a0fa-ced2fa41389e" />

Cara Membuat exe :

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
