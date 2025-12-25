#!/usr/bin/env python3
"""
千问大模型快速客户端
使用方式：
  ag    # 进入对话
  ag -s # 查看服务状态
  ag -k # 停止服务
"""
import os
import sys
import json
import socket
import argparse
import readline
from pathlib import Path

class QwenClient:
    """千问客户端"""
    
    def __init__(self, use_unix=True):
        self.use_unix = use_unix
        if use_unix:
            self.socket_path = '/tmp/qwen_server.sock'
        else:
            self.host = '127.0.0.1'
            self.port = 9898
    
    def connect(self):
        """连接到服务器"""
        try:
            if self.use_unix:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.socket_path)
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((self.host, self.port))
            return sock
        except ConnectionRefusedError:
            print("错误: 服务未启动，请先启动服务")
            print("运行: systemctl start qwen-server")
            return None
        except FileNotFoundError:
            print("错误: 服务未启动，套接字文件不存在")
            print("运行: systemctl start qwen-server")
            return None
    
    def send_request(self, request):
        """发送请求到服务器"""
        sock = self.connect()
        if not sock:
            return None
        
        try:
            # 发送请求
            request_json = json.dumps(request, ensure_ascii=False)
            sock.send(request_json.encode('utf-8') + b"__END__")
            
            # 接收响应
            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"__END__" in response_data:
                    break
            
            # 解析响应
            response_str = response_data.decode('utf-8').replace("__END__", "")
            return json.loads(response_str)
            
        except Exception as e:
            print(f"通信错误: {e}")
            return None
        finally:
            sock.close()
    
    def chat_interactive(self):
        """交互式对话"""
        print("\n" + "="*60)
        print("千问大模型对话模式 (输入 'exit' 退出，'clear' 清空历史)")
        print("="*60 + "\n")
        
        conversation_history = []
        
        while True:
            try:
                # 获取用户输入
                user_input = input("\033[94m你: \033[0m").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'exit':
                    print("退出对话")
                    break
                
                if user_input.lower() == 'clear':
                    conversation_history = []
                    print("\033[93m对话历史已清空\033[0m")
                    continue
                
                # 添加到历史
                conversation_history.append({"role": "user", "content": user_input})
                
                # 发送请求
                print("\033[92m千问: \033[0m", end="", flush=True)
                
                request = {
                    "action": "chat",
                    "messages": conversation_history,
                    "stream": False
                }
                
                response = self.send_request(request)
                
                if response and "response" in response:
                    assistant_reply = response["response"]
                    print(assistant_reply)
                    
                    # 添加到历史
                    conversation_history.append({
                        "role": "assistant", 
                        "content": assistant_reply
                    })
                else:
                    error_msg = response.get("error", "未知错误") if response else "无响应"
                    print(f"\n\033[91m错误: {error_msg}\033[0m")
                    
            except KeyboardInterrupt:
                print("\n\n退出对话")
                break
            except EOFError:
                print("\n\n退出对话")
                break
    
    def check_status(self):
        """检查服务状态"""
        request = {"action": "status"}
        response = self.send_request(request)
        
        if response:
            print("\n服务状态:")
            print("-" * 40)
            for key, value in response.items():
                print(f"{key:20}: {value}")
            print("-" * 40)
        else:
            print("无法连接到服务")
    
    def ping(self):
        """测试连接"""
        request = {"action": "ping"}
        response = self.send_request(request)
        
        if response and response.get("action") == "pong":
            print("服务运行正常 ✓")
            return True
        else:
            print("服务无响应 ✗")
            return False

def create_wrapper_script():
    """创建ag命令包装脚本"""
    script_content = """#!/bin/bash
# ag命令包装器

# 解析参数
case "$1" in
    -s|--status)
        python3 /opt/qwen-fast/client.py --status
        ;;
    -k|--stop)
        sudo systemctl stop qwen-server
        echo "服务已停止"
        ;;
    -h|--help)
        echo "用法: ag [选项]"
        echo "选项:"
        echo "  (无)     进入对话模式"
        echo "  -s      查看服务状态"
        echo "  -k      停止服务"
        echo "  -h      显示此帮助"
        ;;
    *)
        # 如果没有参数，进入对话模式
        python3 /opt/qwen-fast/client.py --chat
        ;;
esac
"""
    
    # 创建ag命令
    ag_path = "/usr/local/bin/ag"
    with open(ag_path, 'w') as f:
        f.write(script_content)
    
    os.chmod(ag_path, 0o755)
    print(f"ag命令已安装到 {ag_path}")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='千问大模型客户端')
    parser.add_argument('--chat', action='store_true', help='进入对话模式')
    parser.add_argument('--status', action='store_true', help='查看服务状态')
    parser.add_argument('--ping', action='store_true', help='测试连接')
    parser.add_argument('--install', action='store_true', help='安装ag命令')
    
    args = parser.parse_args()
    
    client = QwenClient(use_unix=True)
    
    if args.install:
        create_wrapper_script()
    elif args.status:
        client.check_status()
    elif args.ping:
        client.ping()
    else:
        # 默认进入对话模式
        if client.ping():
            client.chat_interactive()
        else:
            print("服务未启动，请先启动服务:")
            print("  sudo systemctl start qwen-server")
            sys.exit(1)

if __name__ == "__main__":
    main()