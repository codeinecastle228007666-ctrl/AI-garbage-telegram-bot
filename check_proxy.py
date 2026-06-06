"""
Проверка SOCKS5 прокси для Telegram.
Запуск: python check_proxy.py
"""

import asyncio
import socket

try:
    from aiohttp_socks import ProxyConnector
    import aiohttp
except ImportError:
    print("Установи aiohttp-socks: pip install aiohttp-socks")
    exit(1)


async def test_proxy(host: str, port: int, name: str = ""):
    label = f"{host}:{port}" + (f" ({name})" if name else "")
    try:
        connector = ProxyConnector.from_url(f"socks5://{host}:{port}")
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                "https://api.telegram.org/bot8960578668:AAGECiQUbRg-u1mULg2OE7AUc1EuAir_dZA/getMe",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    print(f"  [+] {label} - Telegram доступен!")
                    return True
                else:
                    print(f"  [-] {label} - ответ без ok: {data}")
                    return False
    except asyncio.TimeoutError:
        print(f"  [ ] {label} - таймаут")
    except ConnectionRefusedError:
        print(f"  [x] {label} - соединение отклонено")
    except OSError as e:
        print(f"  [x] {label} - {e}")
    except Exception as e:
        print(f"  [x] {label} - {type(e).__name__}: {e}")
    return False


async def check_direct():
    """Проверка прямого подключения к Telegram (без прокси)."""
    print("\nПроверка прямого подключения к api.telegram.org...")
    try:
        _, _, ips = socket.gethostbyname_ex("api.telegram.org")
        print(f"  DNS resolved: {', '.join(ips[:3])}")
    except Exception as e:
        print(f"  DNS error: {e}")

    try:
        connector = aiohttp.TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                "https://api.telegram.org/bot8960578668:AAGECiQUbRg-u1mULg2OE7AUc1EuAir_dZA/getMe",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                print(f"  HTTP {resp.status}")
                if resp.status == 200:
                    print("  Прямое подключение работает!")
                    return True
    except Exception as e:
        print(f"  Прямое подключение НЕ работает: {type(e).__name__}")
    return False


async def main():
    print("=== Проверка подключения к Telegram ===\n")

    # Сначала пробуем напрямую
    direct_ok = await check_direct()

    print("\nПроверка SOCKS5 прокси...\n")

    # Распространённые порты для tgws / SOCKS5
    ports_to_check = [1080, 2080, 8080, 9050, 9150, 1088, 1086, 3128, 9999]

    found = False
    for port in ports_to_check:
        ok = await test_proxy("127.0.0.1", port, "tgws")
        if ok:
            found = True
            break

    if not found:
        print("\nПрокси не найден на стандартных портах.")
        print("Попробуй узнать порт tgws вручную:")
        print("  1. Открой диспетчер задач (Ctrl+Shift+Esc)")
        print("  2. Найди процесс tgws или mtproxy")
        print("  3. Посмотри порт в столбце 'Командная строка' или 'PID'")
        print("\nИли выполни в cmd:")
        print('  netstat -ano | findstr "1080 2080 8080"')
        print("  tasklist /svc | findstr tgws")
        print("\nПосле того как узнаешь порт, пропиши в .env:")
        print("  BOT_PROXY=socks5://127.0.0.1:ПОРТ")

    if not direct_ok and not found:
        print("\nНи прямое подключение, ни прокси не работают.")
        print("Возможно, нужно включить AmneziaVPN или проверить tgws.")

    print()


if __name__ == "__main__":
    asyncio.run(main())
