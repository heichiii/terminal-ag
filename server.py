#!/usr/bin/env python3
"""
千问大模型常驻后台服务
启动后保持模型加载状态，通过Socket提供快速响应
"""
import os
import sys
import json
import socket
import threading
import signal
import syslog
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from llm_client import QwenLLMClient

class QwenServer:
    """千问后台服务"""
    
    def __init__(self, host='127.0.0.1', port=9898):
        self.host = host
        self.port = port
        self.running = True
        self.llm_client = None
        self.socket_path = '/tmp/qwen_server.sock'  # Unix域套接字
        
        # 信号处理
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # 初始化日志
        syslog.openlog("qwen-server", syslog.LOG_PID, syslog.LOG_DAEMON)
    
    def signal_handler(self, signum, frame):
        """处理停止信号"""
        syslog.syslog(syslog.LOG_INFO, f"收到停止信号 {signum}")
        self.running = False
        if self.llm_client:
            self.llm_client.cleanup()
    
    def initialize_llm(self):
        """初始化大模型"""
        try:
            api_key = os.getenv("DASHSCOPE_API_KEY")
            if not api_key:
                syslog.syslog(syslog.LOG_ERR, "未设置 DASHSCOPE_API_KEY")
                return False
            
            self.llm_client = QwenLLMClient(api_key=api_key)
            
            # 预热模型（发送一个简单请求，加载到内存）
            syslog.syslog(syslog.LOG_INFO, "正在预热千问模型...")
            warmup_response = self.llm_client.chat_completion(
                messages=[{"role": "user", "content": "你好"}],
                stream=False
            )
            
            if warmup_response:
                syslog.syslog(syslog.LOG_INFO, f"模型预热成功: {warmup_response[:50]}...")
            else:
                syslog.syslog(syslog.LOG_WARNING, "模型预热无响应，但继续启动")
            
            return True
            
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"模型初始化失败: {str(e)}")
            return False
    
    def handle_client(self, client_socket):
        """处理客户端请求"""
        try:
            # 接收请求数据
            data = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"__END__" in data:
                    break
            
            if not data:
                return
            
            # 解析请求
            request_str = data.decode('utf-8').replace("__END__", "")
            try:
                request = json.loads(request_str)
            except json.JSONDecodeError:
                response = {"error": "无效的JSON请求"}
                client_socket.send(json.dumps(response).encode('utf-8') + b"__END__")
                return
            
            # 处理请求
            response = self.process_request(request)
            
            # 发送响应
            response_json = json.dumps(response, ensure_ascii=False)
            client_socket.send(response_json.encode('utf-8') + b"__END__")
            
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"处理客户端请求时出错: {str(e)}")
            error_response = {"error": f"服务器内部错误: {str(e)}"}
            client_socket.send(json.dumps(error_response).encode('utf-8') + b"__END__")
        finally:
            client_socket.close()
    
    def process_request(self, request):
        """处理不同类型的请求"""
        action = request.get("action", "chat")
        
        if action == "chat":
            return self.process_chat(request)
        elif action == "ping":
            return {"status": "alive", "action": "pong"}
        elif action == "status":
            return self.get_status()
        else:
            return {"error": f"未知操作: {action}"}
    
    def process_chat(self, request):
        """处理对话请求"""
        messages = request.get("messages", [])
        stream = request.get("stream", False)
        
        if not messages:
            return {"error": "消息不能为空"}
        
        try:
            if stream:
                # 流式响应需要特殊处理
                return {"warning": "流式响应需要WebSocket，使用非流式"}
            
            response = self.llm_client.chat_completion(
                messages=messages,
                stream=False,
                temperature=request.get("temperature", 0.9),
                max_tokens=request.get("max_tokens", 2000)
            )
            
            return {
                "response": response,
                "tokens": len(response) // 4  # 估算token数
            }
            
        except Exception as e:
            return {"error": f"模型请求失败: {str(e)}"}
    
    def get_status(self):
        """获取服务状态"""
        return {
            "status": "running",
            "model_loaded": self.llm_client is not None,
            "clients_connected": threading.active_count() - 1,  # 减去主线程
            "memory_usage": self.get_memory_usage()
        }
    
    def get_memory_usage(self):
        """获取内存使用情况"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss // 1024 // 1024  # MB
        except:
            return "unknown"
    
    def run_unix_socket(self):
        """使用Unix域套接字运行（更快）"""
        # 清理旧的套接字文件
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        
        # 创建Unix域套接字
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        server.listen(5)
        
        # 设置套接字权限，允许其他用户连接
        os.chmod(self.socket_path, 0o666)
        
        syslog.syslog(syslog.LOG_INFO, f"Unix套接字服务启动: {self.socket_path}")
        
        while self.running:
            try:
                client, _ = server.accept()
                client_thread = threading.Thread(target=self.handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()
            except Exception as e:
                if self.running:  # 如果不是因为停止导致的异常
                    syslog.syslog(syslog.LOG_ERR, f"接受连接时出错: {str(e)}")
        
        server.close()
        os.remove(self.socket_path)
        syslog.syslog(syslog.LOG_INFO, "服务已停止")
    
    def run_tcp_socket(self):
        """使用TCP套接字运行"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5)
        
        syslog.syslog(syslog.LOG_INFO, f"TCP服务启动: {self.host}:{self.port}")
        
        while self.running:
            try:
                client, addr = server.accept()
                syslog.syslog(syslog.LOG_DEBUG, f"客户端连接: {addr}")
                client_thread = threading.Thread(target=self.handle_client, args=(client,))
                client_thread.daemon = True
                client_thread.start()
            except Exception as e:
                if self.running:
                    syslog.syslog(syslog.LOG_ERR, f"接受连接时出错: {str(e)}")
        
        server.close()
    
    def run(self, use_unix=True):
        """运行服务"""
        syslog.syslog(syslog.LOG_INFO, "千问后台服务启动中...")
        
        # 初始化模型
        if not self.initialize_llm():
            syslog.syslog(syslog.LOG_ERR, "服务启动失败")
            return 1
        
        syslog.syslog(syslog.LOG_INFO, "服务启动成功，等待连接...")
        
        try:
            if use_unix:
                self.run_unix_socket()
            else:
                self.run_tcp_socket()
        except KeyboardInterrupt:
            syslog.syslog(syslog.LOG_INFO, "收到键盘中断")
        finally:
            self.cleanup()
        
        return 0
    
    def cleanup(self):
        """清理资源"""
        if self.llm_client:
            self.llm_client.cleanup()
        syslog.syslog(syslog.LOG_INFO, "服务资源已清理")
        syslog.closelog()

def main():
    """主入口"""
    # 检查是否在systemd下运行
    if os.getenv("INVOCATION_ID"):
        syslog.syslog(syslog.LOG_INFO, "在systemd管理下运行")
    
    # 使用Unix域套接字（更快、更安全）
    server = QwenServer()
    return server.run(use_unix=True)

if __name__ == "__main__":
    sys.exit(main())