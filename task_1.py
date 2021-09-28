"""
1. Написать функцию host_ping(), в которой с помощью утилиты ping
будет проверяться доступность сетевых узлов.
Аргументом функции является список, в котором каждый сетевой узел
должен быть представлен именем хоста или ip-адресом.
В функции необходимо перебирать ip-адреса и проверять
их доступность с выводом соответствующего сообщения
(«Узел доступен», «Узел недоступен»). При этом ip-адрес
сетевого узла должен создаваться с помощью функции ip_address().
"""


from ipaddress import ip_address
from subprocess import Popen, PIPE


def host_ping(list_ip_addresses, timeout=500, requests=1):
    results = {'Доступные узлы': "", 'Недоступные узлы': ""}
    for address in list_ip_addresses:
        try:
            address = ip_address(address)
        except ValueError:
            pass
        proc = Popen(f"ping {address} -w {timeout} -n {requests}",
                     shell=False, stdout=PIPE)
        proc.wait()
        if proc.returncode == 0:
            results['Доступные узлы'] += f"{str(address)}\n"
            res_string = f'{address} - Узел доступен'
        else:
            results['Недоступные узлы'] += f"{str(address)}\n"
            res_string = f'{address} - Узел недоступен'
        print(res_string)
    return results

if __name__ == '__main__':
    ip_addresses = ['yandex.ru', '7.7.7.7', '192.168.0.10', '192.168.0.11']
    host_ping(ip_addresses)


"""
Результат выполнения:

yandex.ru - Узел доступен
7.7.7.7 - Узел недоступен
192.168.0.10 - Узел доступен
192.168.0.11 - Узел доступен

Process finished with exit code 0
"""

"""
Пояснение к IP:
192.168.0.10 - Мой IP-адрес (присваивается автоматически)
"""