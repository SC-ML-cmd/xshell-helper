def Main():
    f = open(r"C:\temp\xsh_test.txt", "w")
    f.write("hello from xshell python\n")

    try:
        import socket
        f.write("SOCKET_OK\n")
    except Exception as e:
        f.write("SOCKET_FAIL:" + str(e) + "\n")

    try:
        import json
        f.write("JSON_OK\n")
    except:
        f.write("JSON_FAIL\n")

    try:
        import threading
        f.write("THREADING_OK\n")
    except:
        f.write("THREADING_FAIL\n")

    try:
        import os
        f.write("OS_OK\n")
    except:
        f.write("OS_FAIL\n")

    f.close()
