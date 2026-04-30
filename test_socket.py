def Main():
    log_path = r"D:\dev\workspace\AI\xshell-helper\test_result.txt"
    try:
        import socket
        with open(log_path, "w") as f:
            f.write("socket OK\n")
            f.write("gethostname: " + socket.gethostname() + "\n")
    except Exception as e:
        with open(log_path, "w") as f:
            f.write("socket FAIL: " + str(e) + "\n")

    try:
        import json
        import threading
        with open(log_path, "a") as f:
            f.write("json OK\n")
            f.write("threading OK\n")
    except Exception as e:
        with open(log_path, "a") as f:
            f.write("json/threading FAIL: " + str(e) + "\n")
