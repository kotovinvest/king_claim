from web3 import Web3
import cloudscraper
import random
from typing import List, Dict
import time
from eth_account.messages import encode_defunct
import json
from fake_useragent import UserAgent
from config import CONFIG
import logging
from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

w3 = Web3()
ua = UserAgent()

def get_address_from_private_key(private_key: str) -> str:
    try:
        account = w3.eth.account.from_key(private_key)
        return account.address
    except Exception as e:
        logger.error(f"Ошибка получения адреса: {str(e)}")
        return f"Error: {str(e)}"

def format_amount(amount: str) -> float:
    try:
        wei_value = int(amount)
        readable = wei_value / 10**18
        return readable
    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка форматирования amount: {amount}, {str(e)}")
        return 0.0

def make_request(url: str, proxy: str, user_agent: str, method: str = "GET", json_data: Dict = None, retries: int = 3) -> Dict:
    scraper = cloudscraper.create_scraper()
    proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    headers = {"User-Agent": user_agent}
    
    for attempt in range(retries):
        try:
            if method == "GET":
                response = scraper.get(url, proxies=proxy_dict, headers=headers, timeout=10)
            elif method == "POST":
                response = scraper.post(url, json=json_data, proxies=proxy_dict, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"Запрос к {url} | Попытка {attempt + 1}/{retries} не удалась: {str(e)}")
                time.sleep(10)
            else:
                logger.error(f"Запрос к {url} | Ошибка после {retries} попыток: {str(e)}")
                return {"error": str(e)}

def check_allocation(address: str, proxy: str, user_agent: str) -> Dict:
    url = f"https://app.ether.fi/api/king/{address}"
    data = make_request(url, proxy, user_agent)
    
    if "error" in data:
        logger.error(f"{address} | Ошибка API: {data['error']}")
        if data.get("amount") == "0":
            return {"address": address, "amount_readable": 0}
        return {"address": address, "error": data["error"]}
    
    amount = data.get("Amount", "0")
    readable_amount = format_amount(amount)
    logger.info(f"{address} | Проверка аллокации | Amount KING: {readable_amount:.16f}")
    return {"address": address, "amount_readable": readable_amount}

def check_pre_order(address: str, proxy: str, user_agent: str) -> bool:
    url = f"https://app.ether.fi/api/cash/pre-order/{address}"
    data = make_request(url, proxy, user_agent)
    return data.get("success", False) and not data.get("hasPreOrder", False)

def check_current_chain(address: str, proxy: str, user_agent: str) -> str:
    url = f"https://app.ether.fi/api/king-claim-chain/{address}"
    data = make_request(url, proxy, user_agent)
    return data.get("chain", "") if data.get("success", False) else ""

def sign_and_claim_network(address: str, private_key: str, network: str, proxy: str, user_agent: str) -> bool:
    url = f"https://app.ether.fi/api/king-claim-chain/{address}"
    message = f"I want to claim my KING tokens on {network}"
    
    try:
        message_hash = encode_defunct(text=message)
        signed_message = w3.eth.account.sign_message(message_hash, private_key=private_key)
        signature = signed_message.signature.hex()
        
        payload = {"address": address, "message": message, "signature": signature}
        data = make_request(url, proxy, user_agent, method="POST", json_data=payload)
        
        if "error" in data:
            logger.error(f"{address} | Клейм сети | Ошибка: {data['error']}")
            return False
        
        if data.get("success", False):
            verify_data = make_request(url, proxy, user_agent)
            if verify_data.get("chain", "") == network:
                logger.info(f"{address} | Клейм сети | Сеть {network} успешно заклеймена!")
                return True
        return False
    except Exception as e:
        logger.error(f"{address} | Подпись/клейм | Ошибка: {str(e)}")
        return False

def process_network_selection(address: str, private_key: str, proxy: str, user_agent: str) -> str:
    current_chain = check_current_chain(address, proxy, user_agent)
    
    if current_chain == "Swell":
        logger.info(f"{address} | Проверка сети | Сеть уже выбрана: Swell")
        return "Успешно"
    elif current_chain:
        logger.info(f"{address} | Проверка сети | Сеть уже выбрана: {current_chain}")
        return "Успешно"
    
    if not check_pre_order(address, proxy, user_agent):
        return "Неуспешно"
    
    if sign_and_claim_network(address, private_key, "Swell", proxy, user_agent):
        return "Успешно"
    return "Неуспешно"

def process_account(private_key: str, proxy: str, config: Dict) -> Dict:
    user_agent = ua.random
    address = get_address_from_private_key(private_key)
    
    if "Error" in address:
        logger.error(f"{address} | Получение адреса | Ошибка приватного ключа")
        return {"address": "Error", "amount": 0, "claim_status": "Неуспешно"}
    
    result = check_allocation(address, proxy, user_agent)
    if "error" in result:
        logger.error(f"{address} | Проверка аллокации | Ошибка: {result['error']}")
        return {"address": address, "amount": 0, "claim_status": "Неуспешно"}
    
    claim_status = "Не выбран"
    if result['amount_readable'] > 0 or config["force_network_selection"]:
        claim_status = process_network_selection(address, private_key, proxy, user_agent)
    
    delay = random.uniform(config["delay_min"], config["delay_max"])
    logger.info(f"{address} | Задержка | Ожидание {delay:.2f} секунд перед следующим ключом")
    time.sleep(delay)
    
    return {"address": address, "amount": result['amount_readable'], "claim_status": claim_status}

def save_to_excel(results: List[Dict], filename: str = "results.xlsx"):
    # Преобразуем данные, чтобы избежать проблем с форматированием чисел
    formatted_results = []
    for result in results:
        formatted_result = {
            "Address": result["address"],
            "KING Amount": f"{result['amount']:.16f}" if result["amount"] != 0 else "0",
            "Claim Status": result["claim_status"]
        }
        formatted_results.append(formatted_result)
    
    # Создаём DataFrame
    df = pd.DataFrame(formatted_results, columns=["Address", "KING Amount", "Claim Status"])
    
    # Сохраняем в Excel с движком xlsxwriter
    try:
        writer = pd.ExcelWriter(filename, engine='xlsxwriter')
        df.to_excel(writer, index=False, sheet_name='Sheet1')
        writer.close()
        logger.info(f"Результаты сохранены в {filename}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении в Excel: {str(e)}")

def load_lines(filename: str) -> List[str]:
    try:
        with open(filename, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
            logger.info(f"Загружено {len(lines)} строк из {filename}")
            return lines
    except FileNotFoundError:
        logger.error(f"Файл {filename} не найден")
        return []

def main():
    config = CONFIG
    private_keys = load_lines("private_keys.txt")
    proxies = load_lines("proxies.txt")
    
    if not private_keys:
        logger.error("private_keys.txt пуст или не найден")
        return
    if not proxies:
        logger.error("proxies.txt пуст или не найден")
        return
    
    logger.info(f"Загружено {len(private_keys)} ключей и {len(proxies)} прокси")
    
    accounts_per_proxy = max(1, config["accounts_per_proxy"])
    required_proxies = (len(private_keys) + accounts_per_proxy - 1) // accounts_per_proxy
    if len(proxies) < required_proxies:
        logger.error(f"Недостаточно прокси: {len(proxies)} < {required_proxies}")
        return
    
    key_proxy_pairs = []
    proxy_index = 0
    for i, private_key in enumerate(private_keys):
        if i % accounts_per_proxy == 0 and proxy_index < len(proxies):
            proxy_index += 1
        key_proxy_pairs.append((private_key, proxies[proxy_index - 1]))
    
    processing_pairs = key_proxy_pairs.copy()
    if config["random_order"]:
        random.shuffle(processing_pairs)
    
    results = [None] * len(private_keys)
    max_threads = max(1, config["max_threads"])
    logger.info(f"Запуск обработки с {max_threads} потоками")
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {executor.submit(process_account, pk, proxy, config): i 
                   for i, (pk, proxy) in enumerate(processing_pairs)}
        result_dict = {}
        for future in as_completed(futures):
            index = futures[future]
            original_index = key_proxy_pairs.index(processing_pairs[index])
            try:
                result = future.result()
                result_dict[original_index] = result
            except Exception as e:
                logger.error(f"Ошибка в потоке для индекса {original_index}: {str(e)}")
                result_dict[original_index] = {"address": "Error", "amount": 0, "claim_status": "Неуспешно"}
        
        for i in range(len(private_keys)):
            results[i] = result_dict.get(i, {"address": "Error", "amount": 0, "claim_status": "Неуспешно"})
    
    save_to_excel(results)

if __name__ == "__main__":
    main()