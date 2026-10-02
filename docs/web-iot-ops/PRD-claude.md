PRD — IoT Ops Ticketing & Task Dashboard (AppSheet)
1. Konteks & Masalah

Tim Managed Service IoT saat ini menjalankan daily ticketing di satu Google Sheet (Master Data Alert Monitoring). Volumenya sudah 54.211 baris tiket (Apr–Agu 2026, ~199 hari aktif, rata-rata ±270 tiket/hari, puncak 845 tiket/hari). Masalah struktural yang aku temukan:

Ticket Action Detail tidak benar-benar tabel. Kolom A–F sheet itu adalah hasil spill dari satu formula di A1:
=QUERY('Master Support Ticket MS'!A:M;"SELECT D,B,H,K,L,M WHERE B != '-' ...")
sedangkan kolom G–K (Corrective Action, Action Type, Close Time, Closed By, checkbox) diisi manual. Artinya urutan baris hasil QUERY dan baris manual hanya "sejajar karena kebetulan". Sekali ada baris disisipkan/dihapus/di-filter di master, seluruh pasangan action bergeser dan salah tiket. Ini risiko integritas data nomor satu.

Ticket Number di-generate dari posisi baris. B2 = IF(LEN(C2&K2)<5;"-";C2&A2&"-"&RIGHT(K2;3)) → Site + nomor urut baris + 3 huruf terakhir Issue Type (mis. BRCB1-ANF). Karena bergantung pada A2 (No urut manual), nomor tiket tidak stabil dan sudah ada 483 baris bernomor - plus 482 nomor duplikat.

Status tiket praktis tidak ada. Kolom Closed By dan Status di Master Support Ticket MS 100% kosong. Di Support Ticket Auto Reporting, kolom STATUS bernilai SOLVED untuk seluruh 141 baris — jadi tidak ada lifecycle Open → In Progress → Closed yang bisa diukur.

Close Time hasil lookup rapuh. P2 = XLOOKUP(B2;'Ticket Action Detail'!B:B;'Ticket Action Detail'!I:I;"Belum Ada";0) — XLOOKUP di kolom 54rb baris, dikalikan 54rb baris. Ini penyebab sheet berat.

Sheet PERFORMANCE MS rusak. Header menampilkan #VALUE! dan #DIV/0! pada AVG RESPONSE TIME, dan tabel harian TECH SUPPORT berisi 0 semua. Dashboard performa efektif tidak berfungsi. Master reporting juga error #REF! di A2 ("Array result was not expanded because it would overwrite data in A267").

Master data tidak terkelola. Unit No punya 2.072 nilai unik tanpa data validation — bebas ketik, jadi banyak varian. Issue Description punya 824 varian yang sebagian besar hanya beda kapitalisasi (datalog offline 5.959×, Datalog offline 4.884×, datalog Offline 2.459×, Datalog Offline 2.399×). Corrective Action/Blocker 1.444 varian (FU IT SITE 19.501×, FU IT Site 820×, fu it site 458×, fu IT SITE 442×). Nama orang pun tidak konsisten: Oditya Andalas Putra vs Oditya Andalas P.

Entry masih satu-satu. Padahal pola kerjanya sangat repetitif — 20.182 tiket bertipe FU ke SITE DATALOG OFF dan 14.121 Request HO. Ini kandidat sempurna untuk bulk entry.

2. Tujuan Produk

Membangun aplikasi AppSheet di atas Google Sheet (tetap sebagai backend) yang: memberi setiap tiket identitas dan status yang sah; memisahkan tiket (header) dari action (detail) sebagai relasi parent–child yang benar; memungkinkan IoT Ops membuat 10–50 tiket dalam hitungan detik lewat bulk/template, bukan satu-satu; menyediakan dashboard real-time bergaya Figma reference untuk shift lead & manajemen; dan mengelola orang, shift, roster, serta beban kerja secara eksplisit.

Target ukuran keberhasilan: waktu input satu batch tiket rutin turun dari ±3 menit jadi <20 detik; nomor tiket duplikat/- jadi 0; varian Issue Description turun dari 824 jadi <60 pilihan terkurasi; AVG response time bisa dihitung otomatis tanpa error.

3. Katalog Field (hasil audit lengkap)
3.1 Master Support Ticket MS (A–P, 54.211 baris)
Kol	Field	Tipe sekarang	Dropdown	Catatan
A	No	angka manual	–	urutan, dipakai formula ticket number
B	Ticket Number	formula	–	53.729 unik, 483 bernilai -
C	Site	dropdown	✅ 16 opsi	terpakai 53.704
D	Date	tanggal	–	199 tanggal (2026/04/01 – 2026/08/05)
E	Start Time	jam	–	timestamp mulai
F	Response Time	jam	–	timestamp respon (bukan durasi)
G	Shift	angka	❌ tak ada validasi	nilai 1 / 2 / 3 (+1 typo 31)
H	First Responder	dropdown	✅ 8 opsi	
I	Closed By	teks	–	kosong total
J	Status	teks	–	kosong total
K	Issue Type	dropdown	✅ 36 opsi	hanya 19 yang pernah dipakai
L	Unit No	teks bebas	❌	2.072 unik
M	Issue Description	teks bebas	❌	824 varian
N	Response Time	–	–	kosong, tidak terpakai
O	Response Time INT	–	–	kosong, tidak terpakai
P	Close Time	XLOOKUP	–	fallback "Belum Ada"
3.2 Ticket Action Detail (A–K, 54.500 baris)

Kolom A–F = mirror QUERY dari master (Date, Ticket Number, First Responder, Issue Type, UnitNo, Issue Description). Yang diisi manual: G Corrective Action/Blocker (teks bebas, 1.444 varian), H Action Type (dropdown ✅ 37 opsi), I Close time (jam), J Closed By (dropdown ✅ 8 opsi), K checkbox (53.662 TRUE / 837 FALSE — sepertinya penanda "sudah ditutup").

3.3 Nilai dropdown — lengkap

Site (16): BRCB · BRCG · ALL SITE · BEKB · HO · TCMM · BRCB & BRCG · KIDE · VIPO · MTBU · BTSJ · GSM · ARIA · KPCS · SMMS · HMNT
Distribusi nyata: BRCB 28.041, BRCG 21.944, BEKB 1.161, TCMM 1.095, MTBU 776, VIPO 214, BTSJ 204, KPCS 164, GSM 49, ARIA 46, sisanya ≤3.

First Responder (8): Tama · Titin Ervina Sari · Oktavia Nur Azizah · Gading Aulia · Oditya Andalas Putra · Muhammad Jibran Hady · Bayu Sutra · Muhamad Alviani
Tama belum pernah muncul di data. Beban: Alviani 11.504 (21%), Bayu 7.454, Gading 7.208, Oktavia 7.124, Oditya 7.068, Jibran 6.939, Titin 6.365.

Closed By (8): sama seperti di atas tapi Tama diganti Gerald. Data aktual masih memuat Oditya Andalas P (1.831×) yang tidak ada di daftar → perlu dinormalisasi.

Issue Type (36 opsi): Closed Eye False CEA · Reposition REP · Datalog Offline DOF · Speed Delay/Spike SPS · Firmware Update FUP · Yawning False YWA · Salah Server IPS · -7 MI7 · Hardware Problem HPO · Request Site REQ · Vlog not create VNT · config corrupt CC · Alert belum masuk ABM · Delete SLS · Request HO · No Face ANF · Laporan Penemuan Alert Berulang PAA · Overspeed SPD · Problem Service Nginx NGX · Service terpause · FU IP Double · False model · No Alert NA · FU ke SITE DATALOG OFF · NTP · Laporan Rekomendasi Observasi LRO · Laporan Rekomendasi · Random Anomaly Checking RAC · Worst Performers Evidence WPE · STORAGE DEVICE · PENGECEKAN FATIGUE · Datalog NULL · Alert Salah · Service Checking · PENGECEKAN SMOKING PHONING
(17 di antaranya belum pernah terpakai — kandidat arsip. Perhatikan: sufiks 3 huruf inilah yang jadi kode tiket, jadi Service terpause, NTP, False model, Datalog NULL, Service Checking menghasilkan kode aneh.)

Action Type (37 opsi): Perubahan Parameter · Update File Config · Pengecekan Parameter · No Action · FU IT Site · Restart Services · Requested Action · Deploy Update Services · Penyesuaian setingan cam · Validasi ulang · Dokumentasi · Deploy Flow Node-red · Install driver iobox · Pengecekan Data · Replay Video · Penyesuaian Volume · Restart CPE · Replace File · Create Table MariaDB · Restart device · Penyesuaian IP Server · Download VLOG · Penyesuaian IP MH · Setting MH unit Baru SMUB · restart servIce RS · Running Job Cleansing · Update mariadb · Penyesuaian · Update Firmware · Create Ticket · Monitoring · Download txt · SPM Problem · Pengecekan Video Alert · DEPLOYMENT ASSITING · FU DEVELOPER · Analisa data
Terpakai: FU IT Site 22.810 (43%), Pengecekan Data 16.126, Validasi ulang 11.696, Requested Action 2.227 — empat ini saja 98% dari semua action.

3.4 Master reporting (dokumen temuan, 569 baris) — dropdown terkait

JUDUL laporan (18): LAPORAN OBSERVASI REAL TIME DAN ANALISA VLOG ORT · LAPORAN PENEMUAN DEVIASI MELALUI OBSERVASI REAL TIME DRT · LAPORAN PENEMUAN PELANGGARAN KONTEKS "BENAR" PKT · LAPORAN REKOMENDASI INTERVENSI LRI · LAPORAN PENEMUAN ALERT LPA · LAPORAN ANALISA ALERT BERULANG AAB · LAPORAN FORMALISASI BLASTING LFB · LAPORAN PENEMUAN PELANGGARAN DISTARKSI/TIDAK FOKUS PPD · LAPORAN ANALISA POTENSI ALERT BERULANG PAB · Laporan Penemuan Anomali Alert PAA · LAPORAN ANALISA OVERSPEED LAO · LAPORAN PENEMUAN ANOMALY WEB LAW · LAPORAN ANALISA ALERT NOFACE AAF · LAPORAN FALSE MODEL CONTROL ROOM LFM · LAPORAN OBSERVASI INSIDEN LOI · LAPORAN REKOMENDASI OBSERVASI HIGHRISK LAH · LAPORAN ANALISA OVERSPEED WARNING LAOW · LAPORAN SPEAK UP SITE

SITE laporan (3): BRCB · BRCG · ALLSITE — tidak konsisten dengan ALL SITE di ticket sheet.
SHIFT (3): 1 · 2 · 3
PIC HO (23): M. Hasya · Titin Ervina Sari · Raihan Fadhil · Muhammad Taufiq Azra · Muhammad Putra Tama · Zidan Ferdiansyah · Destry Zumar Sastiani · Andy Law Simbolon · Yoses Dwi Maheswara · A.A Rafid Raihan · Jihan · Fauzan Acyuto · Oktavia Nur Azizah · Gading Aulia · Bayu · Arya · Jibran · Zahid · Gerald · Alvian · Shifa · Febri · Divo
Perhatikan: Bayu/Bayu Sutra, Jibran/Muhammad Jibran Hady, Alvian/Muhamad Alviani, Tama/Muhammad Putra Tama — orang yang sama, tiga ejaan. Ini yang harus dibereskan lewat tabel People tunggal.

4. Data Model AppSheet Usulan

Prinsipnya: pecah jadi tabel referensi + dua tabel transaksi dengan relasi eksplisit, hilangkan semua formula lintas-sheet.

Tabel referensi (jadi sumber semua dropdown, bukan lagi data validation yang di-hardcode per range): REF_Site (kode, nama, region, aktif), REF_IssueType (kode 3-huruf eksplisit sebagai kolom sendiri, nama, kategori, default SLA menit, aktif), REF_ActionType (nama, kategori, aktif, butuh evidence?), REF_IssueTemplate (Issue Type → daftar Issue Description terkurasi), REF_CorrectiveTemplate (Action Type → daftar corrective action terkurasi), REF_Unit (Unit No, SN, tipe unit, site, IP, status hire/offhire — diperkaya dari sheet IPVHMS), REF_DocType (18 judul laporan + kode).

Tabel orang: People (PersonID, Nama lengkap, nama panggilan/alias, email, role, tim, site penempatan, aktif) — satu baris per orang, semua alias lama di-map ke sini. Roster (PersonID, tanggal, shift, tipe: kerja/off/cuti). Team (Support / Engineering / HO Analyst dst., mengikuti pola "Support Team / Engineering Team" di Figma).

Tabel transaksi: Tickets — TicketID (UNIQUEID(), primary key sebenarnya), TicketNo (nomor readable yang di-generate sekali saat create lalu dibekukan), Date, Site, UnitRef, IssueTypeRef, IssueDescription, Shift, StartTime, ResponseTime, FirstResponderRef, Status, Priority, SLADueAt, ClosedAt, ClosedByRef, BatchID, Source. TicketActions — ActionID, TicketID (ref ke Tickets), Sequence, ActionTypeRef, CorrectiveAction, Blocker, StartedAt, ClosedAt, PerformedByRef, Evidence (image/file), IsFinal. Satu tiket boleh punya banyak action; Tickets.Status dihitung dari action terakhir, bukan dari XLOOKUP.

Status lifecycle usulan (menggantikan STATUS yang selalu SOLVED): New → Open → In Progress → Waiting Site / Waiting Developer (stop-clock SLA) → Resolved → Closed, plus Cancelled / Duplicate. Ini juga yang dipakai kartu KPI di Figma (Open / New / In Process / Closed).

5. UX/UI — mengikuti Figma reference

Struktur navigasi di Figma (Dashboard · Inbox · Ticket Assignment · Ticket Topics · SLA Management · Custom Ticket Status · Automation · Saved Answers · Team work · Joint Editing · Email Integration · Report and Statistics · Settings) aku petakan ke konteks IoT Ops jadi:

Dashboard. Empat kartu KPI persis pola Figma — Open Tickets, New Tickets, In Process, Closed — masing-masing dengan delta "vs shift sebelumnya". Lalu donut Tickets by Issue Type (Figma memakai donut dengan angka besar di tengah + legend berpersentase), bar chart Response Time Trend per hari dengan satu bar highlight untuk hari terpilih, dan tabel Latest Tickets (Ticket ID · Unit · Site · Issue · Umur · Status chip berwarna). Filter global: rentang tanggal, site, shift, engineer. Tombol Export di kanan atas.

Ticket Inbox. Layout tiga panel seperti frame Inbox: kiri folder (Semua, Milik saya, Belum diambil, Overdue SLA, Menunggu Site, Ditutup), tengah list tiket dengan checkbox per baris + action bar bulk di atasnya (assign, ubah status, tambah action, tutup, hapus-batal), kanan detail tiket + timeline action + form quick-action.

Ticket Assignment. Kartu per tim dengan metrik Members / Active Tickets / Avg Response Time (sama seperti Figma), lalu Assignment Rules dengan toggle on/off: contoh rule IoT Ops — "Issue Type = FU ke SITE DATALOG OFF → assign ke engineer on-shift dengan beban terendah", "Site = BRCB & shift 3 → Engineer A".

Ticket Topics menjadi manajemen REF_IssueType + REF_ActionType + template deskripsi. SLA Management menjadi konfigurasi target response/resolution per Issue Type + kalender stop-clock. Automation menjadi Apps Script/AppSheet Bot: auto-close resolved > N hari, eskalasi kalau belum direspon > 4 jam, ringkasan shift otomatis. Report and Statistics menggantikan PERFORMANCE MS yang rusak.

Visual language: aksen hijau (
#00C48C-ish) seperti Figma, kartu putih radius besar di atas latar abu muda, status chip pill berwarna, sidebar kiri terang. Untuk AppSheet ini diterjemahkan lewat Brand color, Card/Deck/Table view, dan format rules berwarna.

6. Fitur Input Cepat (inti permintaan kamu)

Bulk Create Wizard. Satu form dengan header bersama (Date, Site, Shift, Issue Type, First Responder, Start Time) + satu field multi-line untuk menempel daftar Unit No. 30 unit ditempel = 30 tiket dibuat sekaligus dengan satu BatchID. Ini menggantikan pola paling dominan di data kamu (FU Datalog Off & Request HO).

Quick Task Templates. Template siap pakai yang mengisi Issue Type + Issue Description + Action Type + Corrective Action sekaligus, dibuat dari 6 pola terbanyak yang aku lihat: FU Datalog Offline, Request HO (HR/roster/deployment), No Face ANF, Pengecekan Fatigue, Hardware Problem, Overspeed. Satu tap = form 80% terisi.

Kanban drag & drop. Board berkolom status; drag kartu tiket antar kolom mengubah status + mencatat action otomatis. Board kedua berkolom engineer untuk drag-assign — ini cara paling cepat membagi beban di awal shift. (Catatan teknis penting: AppSheet tidak punya drag-drop kanban native. Ini perlu HTML/JS view yang disematkan, atau alternatifnya "swipe action" + bulk-select AppSheet native. Ada di pertanyaan no. 9.)

Bulk Close. Pilih banyak tiket → satu form Action Type + Corrective Action + Close Time → semua ditutup sekaligus.

Barcode/QR scan Unit No untuk mengisi unit tanpa mengetik, dan voice-to-text untuk field deskripsi di lapangan.

Shift handover. Saat shift berakhir, tiket open otomatis dirangkum jadi catatan handover ke shift berikutnya (menggantikan proses copy-paste manual yang sekarang ada di sheet Support Ticket Auto Reporting).

7. Migrasi

Fase 1: bangun tabel referensi & People, normalisasi alias nama dan varian teks. Fase 2: bekukan TicketNo yang ada jadi nilai statis (bukan formula), generate TicketID, perbaiki 483 nomor -. Fase 3: rekonstruksi relasi Tickets↔TicketActions berdasarkan pasangan baris saat ini (perlu verifikasi manual pada sample). Fase 4: pindahkan data ke sheet backend baru, arsipkan sheet lama read-only. Fase 5: bangun AppSheet UI. Fase 6: paralel-run satu shift, lalu cutover.

Risiko utama: 54rb baris mendekati batas nyaman AppSheet + Google Sheets. Rekomendasi kuat — pisahkan data aktif (90 hari terakhir) dan arsip, atau pindah backend ke Cloud SQL / BigQuery kalau volume tetap ~8rb tiket/bulan.

Pertanyaan yang aku perlu jawabannya

Ini yang paling menentukan bentuk akhir, jadi jawab yang mana pun yang kamu sudah tahu — sisanya bisa kita asumsikan dulu.

Ticket number. Boleh aku ganti formatnya jadi stabil, misalnya BRCB-20260805-0142 (site–tanggal–urut harian)? Atau format BRCB1-ANF yang sekarang wajib dipertahankan karena dipakai di laporan ke klien?
Relasi tiket–action. Satu tiket bisa punya berapa action realistisnya? Data sekarang tampak 1:1 (54.211 vs 54.500 baris). Kalau memang 1:1, apakah kamu mau tetap 1:1 (lebih sederhana) atau memang butuh multi-action per tiket?
Status. Kolom Status kosong total dan reporting selalu SOLVED. Apakah memang semua tiket selesai dalam shift yang sama, atau ada tiket menggantung berhari-hari yang saat ini tidak tercatat? Lifecycle 7-status yang aku usulkan di §4 cocok, atau terlalu banyak?
SLA. Apakah sudah ada target response/resolution time resmi? Per Issue Type atau satu angka global? Dan apakah waktu tunggu ke IT Site / developer dihitung (stop-clock) atau tidak? Ini menentukan angka "Avg Response Time" di dashboard.
Orang & role. Berapa total orang yang akan pakai app ini, dan role apa saja yang perlu dibedakan? Dugaanku minimal: IoT Ops engineer (input + close), Shift Lead (assign + monitor), HO Analyst (Master reporting), Manager (view + export). Betul? Dan siapa saja yang aktif sekarang — daftar First Responder ada 8 nama, PIC HO ada 23 nama, banyak yang duplikat ejaan. Boleh kirim daftar resmi nama + email + role?
Unit master. 2.072 Unit No tanpa validasi. Apakah ada master unit yang lengkap di file lain (sheet IPVHMS di workbook ini hanya 5 baris)? Tanpa itu, Unit No terpaksa tetap teks bebas dan kualitas data akan tetap kotor.
Issue Type & Action Type cleanup. Dari 36 Issue Type, 17 belum pernah terpakai; dari 37 Action Type, 4 saja sudah 98% pemakaian. Boleh aku arsipkan yang tidak terpakai supaya dropdown ringkas, atau semua harus tetap tersedia?
Issue Description & Corrective Action. Mau aku ubah jadi dropdown terkurasi (~40–60 pilihan hasil clustering, dengan opsi "Lainnya" + free text), atau tetap free text penuh?
Drag & drop. AppSheet native tidak punya kanban drag-drop. Pilih mana: (a) tetap 100% AppSheet, pakai bulk-select + swipe action (cepat dibangun, drag-drop tidak ada), (b) AppSheet + satu HTML view custom untuk board drag-drop (butuh Apps Script web app), atau (c) sekalian bangun web app sendiri (React) dengan Sheets/BigQuery sebagai backend — paling bebas secara UI dan paling mirip Figma, tapi bukan AppSheet lagi. Ini keputusan terbesarnya.
Volume & backend. 54rb baris dan tumbuh ~8rb/bulan. Setuju kalau kita pisah data aktif vs arsip? Atau kamu terbuka pindah ke Cloud SQL/BigQuery?
Scope Master reporting. Sheet dokumen temuan (569 baris, 18 jenis laporan, error #REF!) — masuk scope app ini sebagai modul terpisah, atau tahap berikutnya?
Device & offline. Engineer input dari desktop control room, HP di lapangan, atau dua-duanya? Perlu mode offline?
Notifikasi. Perlu push/email/WhatsApp untuk assignment baru dan SLA breach?
Evidence. Perlu upload foto/screenshot/file per action? Data sekarang tidak punya kolom evidence sama sekali (kecuali Master reporting yang menyimpan nama file PDF sebagai teks).
Deliverable PRD. Mau aku simpan PRD ini sebagai Google Doc di Drive kamu, atau cukup kamu copy dari sini?