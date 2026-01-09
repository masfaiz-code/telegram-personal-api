 from pyrogram import Client
 
 API_ID = input("Masukkan API_ID: ")
 API_HASH = input("Masukkan API_HASH: ")
 
 with Client("session_generator", api_id=int(API_ID), api_hash=API_HASH) as app:
     session_string = app.export_session_string()
     print("\n" + "=" * 50)
     print("SESSION_STRING (simpan ini):")
     print("=" * 50)
     print(session_string)
     print("=" * 50)
