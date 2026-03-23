Update 2.5 :
1.  Import Excel File  (Keywoard) -> pilih platform bulk method
2.  Filter lokasi scrapping
3.  Fixing Bug maps_place_name excel
4.  Bar progress persentase scrapping
5.  spesifik di filter daerah (contoh bantul) di pencarian maps. contoh {nama toko} + {nama daerah yang dipilih}. untuk fokus pencarian toko di daerah yang dipilih bukan cabang lain beda provinsi
6.  Kasus unik Blibli ( Sudah Diperbaiki ), jika barang yang dicari tidak ada di bantul. sebelum diperbaiki, filter lokasi nya tidak ada pilihan 'bantul', tapi aplikasi akan tetap scrapping. Contoh: coba cari 'nitendo', 'dvr' atau 'pabx' di Blibli.com dan ketik filter lokasi 'Bantul', maka tidak ada pilihan 'Bantul' karena tidak ada penjual (toko) disitu. jadi aplikasi dibuat langsung stop tidak melanjutkan scrapping (karena tidak ada toko di Bantul)
7.  fixing minor bug
8.  tampilan waktu lama scrapping
9.  Excel Tersimpan di folder 'data'

*Note : masih banyak kecampur data tampil di platform online shop kabupaten Bantul dan kabupaten lain (Sleman). jadi di excel masih ada banyak diluar ring

<img width="1187" height="908" alt="Screenshot 2026-03-21 090810" src="https://github.com/user-attachments/assets/f854c4a3-25bf-4a8b-8753-2c83dacf93b9" />

<img width="1177" height="909" alt="Screenshot 2026-03-21 090741" src="https://github.com/user-attachments/assets/9cc07454-48ca-4504-abce-33d7b76c6905" />


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
