import asyncio
import aiohttp
import json

async def get_token():
    """Получение access token от AmoCRM"""
    
    # Данные для авторизации
    client_id = "ВАШ_CLIENT_ID"
    client_secret = "ВАШ_CLIENT_SECRET"
    auth_code = "КОД_АВТОРИЗАЦИИ"
    redirect_uri = "ВАШ_REDIRECT_URI"
    domain = "ВАШ_ДОМЕН.amocrm.ru"
    
    url = f"https://{domain}/oauth2/access_token"
    
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri
    }

async def refresh_amocrm_token():
    """Обновление access token"""
    global AMOCRM_ACCESS_TOKEN
    
    AMOCRM_REFRESH_TOKEN = os.getenv("AMOCRM_REFRESH_TOKEN", "")
    
    if not AMOCRM_REFRESH_TOKEN:
        logging.warning("Не настроен refresh token")
        return False
    
    try:
        url = f"https://{AMOCRM_DOMAIN}/oauth2/access_token"
        
        data = {
            "client_id": AMOCRM_CLIENT_ID,
            "client_secret": AMOCRM_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": AMOCRM_REFRESH_TOKEN,
            "redirect_uri": AMOCRM_REDIRECT_URI
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    AMOCRM_ACCESS_TOKEN = result['access_token']
                    
                    # Обновляем .env файл
                    update_env_file('AMOCRM_ACCESS_TOKEN', AMOCRM_ACCESS_TOKEN)
                    update_env_file('AMOCRM_REFRESH_TOKEN', result.get('refresh_token', AMOCRM_REFRESH_TOKEN))
                    
                    logging.info("Токен AmoCRM обновлен")
                    return True
                else:
                    logging.error(f"Ошибка обновления токена: {response.status}")
                    return False
    except Exception as e:
        logging.error(f"Ошибка при обновлении токена: {e}")
        return False

def update_env_file(key: str, value: str):
    """Обновляем значение в .env файле"""
    try:
        with open('.env', 'r') as f:
            lines = f.readlines()
        
        with open('.env', 'w') as f:
            for line in lines:
                if line.startswith(f"{key}="):
                    f.write(f"{key}={value}\n")
                else:
                    f.write(line)
    except Exception as e:
        logging.error(f"Ошибка обновления .env файла: {e}")
            
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            if response.status == 200:
                result = await response.json()
                print("✅ Токен получен успешно!")
                print(json.dumps(result, indent=2))
                
                # Сохраняем токены
                with open('tokens.json', 'w') as f:
                    json.dump(result, f, indent=2)
                
                return result
            else:
                print(f"❌ Ошибка: {response.status}")
                print(await response.text())
                return None

if __name__ == "__main__":
    asyncio.run(get_token())