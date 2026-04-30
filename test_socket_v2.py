def Main():
    # 最简单的写入测试 - 验证脚本是否能运行
    f = open(r"D:\dev\workspace\AI\xshell-helper\test_socket_v2_result.txt", "w")
    try:
        import socket
        f.write("SOCKET_OK\n")
        f.write("gethostname=" + socket.gethostname() + "\n")
    except Exception as e:
        f.write("SOCKET_FAIL:" + str(e) + "\n")

    try:
        import json
        f.write("JSON_OK\n")
    except Exception as e:
        f.write("JSON_FAIL:" + str(e) + "\n")

    try:
        import threading
        f.write("THREADING_OK\n")
    except Exception as e:
        f.write("THREADING_FAIL:" + str(e) + "\n")

    try:
        import os
        f.write("OS_OK\n")
    except Exception as e:
        f.write("OS_FAIL:" + str(e) + "\n")

    f.close()
