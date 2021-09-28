"""
2. Написать функцию host_range_ping() для перебора ip-адресов из заданного диапазона.
Меняться должен только последний октет каждого адреса.
По результатам проверки должно выводиться соответствующее сообщение.
"""


from ipaddress import ip_address
from task_1 import host_ping


def host_range_ping():
    while True:
        start_ip = input('Введите первоначальный адрес: ')
        try:
            las_oct = int(start_ip.split('.')[3])
            break
        except Exception as e:
            print(e)
    while True:
        end_ip = input('Сколько адресов проверить? Введите количество: ')
        if not end_ip.isnumeric():
            print('Необходимо ввести число!')
        else:
            if (las_oct+int(end_ip)) > 254:
                print(f"Можно менять только последний октет, "
                      f"максимальное число хостов для проверки: {254-las_oct}")
            else:
                break

    host_list = []
    [host_list.append(str(ip_address(start_ip)+x)) for x in range(int(end_ip))]
    return host_ping(host_list)

if __name__ == '__main__':
    host_range_ping()


"""
Результат выполнения:

Введите первоначальный адрес: 192.168.0.10
Сколько адресов проверить? Введите количество: 5
192.168.0.10 - Узел доступен
192.168.0.11 - Узел доступен
192.168.0.12 - Узел недоступен
192.168.0.13 - Узел недоступен
192.168.0.14 - Узел недоступен

Process finished with exit code 0
"""
