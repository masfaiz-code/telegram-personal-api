 # Telegram Personal API
 
 REST API untuk mengirim pesan Telegram menggunakan akun personal (bukan bot). Cocok untuk integrasi dengan N8N atau automation tools lainnya.
 
 ## Features
 
 - Kirim pesan ke user/group/channel menggunakan akun personal
 - Authentication menggunakan Bearer token (API Key)
 - Production-ready dengan error handling lengkap
 - Siap deploy ke Zeabur, Railway, atau platform cloud lainnya
 
 ## Environment Variables
 
 Buat file `.env` di root project:
 
 ```env
 API_ID=your_api_id
 API_HASH=your_api_hash
 SESSION_STRING=your_session_string
 API_KEY=your_secret_api_key
 ```
 
 ### Cara Mendapatkan Credentials
 
 1. **API_ID & API_HASH**: 
    - Buka https://my.telegram.org
    - Login dengan nomor telepon
    - Pergi ke "API development tools"
    - Buat aplikasi baru dan catat API_ID dan API_HASH
 
 2. **SESSION_STRING**:
    - Jalankan script generator:
    ```bash
    pip install pyrogram tgcrypto
    python generate_session.py
    ```
    - Masukkan API_ID, API_HASH, dan nomor telepon
    - Masukkan kode OTP yang dikirim ke Telegram
    - Salin session string yang dihasilkan
 
 3. **API_KEY**:
    - Buat secret key yang kuat untuk authentication
    - Contoh: `openssl rand -hex 32`
 
 ## Setup Lokal
 
 ```bash
 # Clone repository
 git clone https://github.com/YOUR_USERNAME/telegram-personal-api.git
 cd telegram-personal-api
 
 # Buat virtual environment
 python -m venv venv
 source venv/bin/activate  # Linux/Mac
 # atau
 venv\Scripts\activate  # Windows
 
 # Install dependencies
 pip install -r requirements.txt
 
 # Buat file .env dan isi credentials
 cp .env.example .env
 
 # Jalankan server
 python main.py
 # atau
 uvicorn main:app --reload --host 0.0.0.0 --port 8000
 ```
 
 ## API Endpoints
 
 ### Health Check
 ```
 GET /health
 ```
 
 ### Get Account Info
 ```
 GET /me
 Authorization: Bearer YOUR_API_KEY
 ```
 
 ### Send Message
 ```
 POST /send-message
 Authorization: Bearer YOUR_API_KEY
 Content-Type: application/json
 
 {
     "chat_id": "@username atau numeric_id",
     "message": "Pesan yang akan dikirim"
 }
 ```
 
 ## Testing dengan cURL
 
 ### Health Check
 ```bash
 curl http://localhost:8000/health
 ```
 
 ### Get Account Info
 ```bash
 curl -X GET http://localhost:8000/me \
   -H "Authorization: Bearer YOUR_API_KEY"
 ```
 
 ### Send Message
 ```bash
 curl -X POST http://localhost:8000/send-message \
   -H "Authorization: Bearer YOUR_API_KEY" \
   -H "Content-Type: application/json" \
   -d '{"chat_id": "@username", "message": "Hello from API!"}'
 ```
 
 ### Send Message ke Chat ID Numeric
 ```bash
 curl -X POST http://localhost:8000/send-message \
   -H "Authorization: Bearer YOUR_API_KEY" \
   -H "Content-Type: application/json" \
   -d '{"chat_id": "123456789", "message": "Hello from API!"}'
 ```
 
 ## Deploy ke Zeabur
 
 1. Push code ke GitHub repository
 2. Buka https://zeabur.com dan login
 3. Create new project
 4. Deploy dari GitHub repository
 5. Tambahkan environment variables di Zeabur dashboard:
    - `API_ID`
    - `API_HASH`
    - `SESSION_STRING`
    - `API_KEY`
 6. Zeabur akan otomatis detect Python dan deploy
 
 ## Integrasi dengan N8N
 
 1. Tambahkan node "HTTP Request"
 2. Method: POST
 3. URL: `https://your-app.zeabur.app/send-message`
 4. Authentication: Header Auth
    - Name: `Authorization`
    - Value: `Bearer YOUR_API_KEY`
 5. Body (JSON):
    ```json
    {
        "chat_id": "{{$node.previous.json.chat_id}}",
        "message": "{{$node.previous.json.message}}"
    }
    ```
 
 ## Error Codes
 
 | Code | Description |
 |------|-------------|
 | 400  | Bad request (invalid parameters) |
 | 401  | Invalid API key atau session expired |
 | 403  | Not participant / private channel |
 | 404  | Chat/user not found |
 | 429  | Rate limited (Telegram flood wait) |
 | 500  | Server error |
 
 ## Security Notes
 
 - Jangan pernah commit file `.env` ke repository
 - Gunakan API_KEY yang kuat dan unik
 - SESSION_STRING adalah kredensial sensitif, jaga kerahasiaannya
 - Pertimbangkan untuk merotasi API_KEY secara berkala
 
 ## License
 
 MIT
