"""
优化的千问客户端，支持连接池和缓存
"""
import os
import json  # 添加这行！
import sys
from typing import List, Dict, Optional
from openai import OpenAI
import syslog
import hashlib
import time

class QwenLLMClient:
    """优化的大模型客户端"""
    
    def __init__(self, api_key: str, base_url: str = None):
        self.base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_key = api_key
        self.model = "qwen-turbo"  # 使用响应更快的模型
        
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60.0,  # 增加超时时间
            max_retries=3  # 增加重试次数
        )
        
        # 简单的响应缓存（可选的优化）
        self.cache = {}
        self.cache_ttl = 300  # 缓存5分钟
        
        syslog.syslog(syslog.LOG_INFO, "千问客户端初始化完成")
    
    def _get_cache_key(self, messages, **kwargs):
        """生成缓存键"""
        key_data = json.dumps({"messages": messages, **kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def chat_completion(self, messages, stream=False, **kwargs):
        """聊天补全，支持缓存"""
        # 如果是流式请求，不使用缓存
        if stream:
            return self._direct_request(messages, stream=True, **kwargs)
        
        # 检查缓存
        cache_key = self._get_cache_key(messages, **kwargs)
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if time.time() - cached_data["timestamp"] < self.cache_ttl:
                syslog.syslog(syslog.LOG_DEBUG, "使用缓存响应")
                return cached_data["response"]
        
        # 发送请求
        response = self._direct_request(messages, stream=False, **kwargs)
        
        # 缓存响应
        if response:
            self.cache[cache_key] = {
                "response": response,
                "timestamp": time.time()
            }
        
        return response
    
    def _direct_request(self, messages, stream=False, **kwargs):
        """直接发送请求"""
        try:
            params = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
                "temperature": kwargs.get("temperature", 0.9),
                "max_tokens": kwargs.get("max_tokens", 1500),
            }
            if stream:
                # 返回一个迭代器，按块产出内容
                return self._stream_response(params)
            else:
                response = self.client.chat.completions.create(**params)
                if response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content
                return ""
                
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"千问请求失败: {str(e)}")
            return None
    
    def _stream_response(self, params):
        """处理流式响应"""
        try:
            response = self.client.chat.completions.create(**params)
            for chunk in response:
                try:
                    delta = chunk.choices[0].delta
                except Exception:
                    continue
                # delta may not always contain content (e.g. meta chunks)
                content = getattr(delta, 'content', None)
                if content:
                    yield content
        except Exception as e:
            syslog.syslog(syslog.LOG_ERR, f"流式响应错误: {str(e)}")
            return
    
    def cleanup(self):
        """清理资源"""
        self.cache.clear()
        syslog.syslog(syslog.LOG_INFO, "客户端资源已清理")