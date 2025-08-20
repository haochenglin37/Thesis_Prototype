#!/bin/bash

# 設置 IP 隔離的 Network Namespace

echo "Setting up IP isolation for MQTT forwarding..."

# 檢查是否為 root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

# 清理可能存在的舊設置
echo "Cleaning up existing setup..."
ip netns del ns_forwarder 2>/dev/null || true
ip link del veth_fwd_host 2>/dev/null || true

# 1. 創建 network namespace
echo "Creating network namespace 'ns_forwarder'..."
ip netns add ns_forwarder

# 2. 創建 veth pair
echo "Creating veth pair..."
ip link add veth_fwd_host type veth peer name veth_fwd_ns

# 3. 將一端放入 namespace
echo "Moving veth_fwd_ns to namespace..."
ip link set veth_fwd_ns netns ns_forwarder

# 4. 配置主機端 (192.168.100.1)
echo "Configuring host side (192.168.100.1)..."
ip addr add 192.168.100.1/24 dev veth_fwd_host
ip link set veth_fwd_host up

# 5. 配置 namespace 端 (192.168.100.2)
echo "Configuring namespace side (192.168.100.2)..."
ip netns exec ns_forwarder ip addr add 192.168.100.2/24 dev veth_fwd_ns
ip netns exec ns_forwarder ip link set veth_fwd_ns up
ip netns exec ns_forwarder ip link set lo up

# 6. 設置 namespace 的路由
echo "Setting up routing..."
ip netns exec ns_forwarder ip route add default via 192.168.100.1

# 7. 啟用主機的 IP 轉發
echo "Enabling IP forwarding..."
sysctl net.ipv4.ip_forward=1

# 8. 設置 NAT（讓 namespace 可以訪問外網）
echo "Setting up NAT..."
iptables -t nat -C POSTROUTING -s 192.168.100.0/24 -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -s 192.168.100.0/24 -j MASQUERADE

# 9. 測試連接
echo ""
echo "=== Testing connectivity ==="
echo "Ping from namespace to host:"
ip netns exec ns_forwarder ping -c 2 192.168.100.1

echo ""
echo "Ping from namespace to external (8.8.8.8):"
ip netns exec ns_forwarder ping -c 2 8.8.8.8

echo ""
echo "Testing route to main MQTT broker:"
ip netns exec ns_forwarder ip route get 192.168.254.139

echo ""
echo "=== Setup Complete ==="
echo "Edge Broker IP:    192.168.254.191 (receives sensor data)"
echo "Forwarder IP:      192.168.100.2 (in ns_forwarder namespace)"
echo "Host Bridge IP:    192.168.100.1"
echo ""
echo "Next step: Test MQTT connection from namespace"
