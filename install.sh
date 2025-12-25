#!/bin/bash
# 千问快速服务安装脚本

set -e

echo "安装千问快速服务..."

# 1. 创建专用用户
if ! id "qwenuser" &>/dev/null; then
    sudo useradd -r -s /usr/sbin/nologin -m qwenuser
    echo "创建用户 qwenuser"
fi

# 2. 创建应用目录
sudo mkdir -p /opt/qwen-fast
sudo chown qwenuser:qwenuser /opt/qwen-fast

# 3. 复制文件
echo "复制文件到 /opt/qwen-fast..."
sudo cp -r ./* /opt/qwen-fast/
sudo chown -R qwenuser:qwenuser /opt/qwen-fast

# 4. 安装Python依赖
echo "安装Python依赖..."
sudo -u qwenuser bash -c "cd /opt/qwen-fast && pip install -r requirements.txt"

# 5. 配置API Key
if [ -n "$DASHSCOPE_API_KEY" ]; then
    echo "设置API Key..."
    sudo tee /etc/default/qwen-server > /dev/null <<EOF
DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY
EOF
else
    echo "警告: 未设置 DASHSCOPE_API_KEY 环境变量"
    echo "请手动编辑 /etc/default/qwen-server"
    sudo tee /etc/default/qwen-server > /dev/null <<EOF
# 请在此处设置你的API Key
# DASHSCOPE_API_KEY=your_actual_key_here
EOF
fi

# 6. 安装systemd服务
echo "安装systemd服务..."
sudo cp /opt/qwen-fast/qwen-server.service /etc/systemd/system/
sudo systemctl daemon-reload

# 7. 安装ag命令
echo "安装ag命令..."
sudo cp /opt/qwen-fast/client.py /usr/local/bin/ag-client
sudo chmod +x /usr/local/bin/ag-client

# 创建ag包装器
sudo tee /usr/local/bin/ag > /dev/null <<'EOF'
#!/bin/bash
if [ "$1" = "-s" ] || [ "$1" = "--status" ]; then
    python3 /opt/qwen-fast/client.py --status
elif [ "$1" = "-k" ] || [ "$1" = "--stop" ]; then
    sudo systemctl stop qwen-server
    echo "服务已停止"
elif [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "千问大模型快速客户端"
    echo "用法: ag [选项]"
    echo "选项:"
    echo "  (无参数)  进入对话模式"
    echo "  -s, --status  查看服务状态"
    echo "  -k, --stop    停止后台服务"
    echo "  -h, --help    显示帮助信息"
else
    # 检查服务状态
    if systemctl is-active --quiet qwen-server; then
        python3 /opt/qwen-fast/client.py --chat
    else
        echo "服务未运行，正在启动..."
        sudo systemctl start qwen-server
        sleep 3  # 等待服务启动
        if systemctl is-active --quiet qwen-server; then
            python3 /opt/qwen-fast/client.py --chat
        else
            echo "启动失败，请检查日志: sudo journalctl -u qwen-server"
        fi
    fi
fi
EOF

sudo chmod +x /usr/local/bin/ag

# 8. 启动服务
echo "启动服务..."
sudo systemctl enable qwen-server
sudo systemctl start qwen-server

echo "安装完成！"
echo ""
echo "使用方法："
echo "1. 直接输入 'ag' 进入对话"
echo "2. 输入 'ag -s' 查看服务状态"
echo "3. 输入 'ag -k' 停止服务"
echo ""
echo "第一次启动可能需要一些时间加载模型..."
echo "查看日志: sudo journalctl -u qwen-server -f"