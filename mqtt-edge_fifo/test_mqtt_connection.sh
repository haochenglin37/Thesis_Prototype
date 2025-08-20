#!/bin/bash

# 測試從 namespace 連接到主 MQTT broker

echo "Testing MQTT connection from isolated IP..."

# 檢查 namespace 是否存在
if ! ip netns list | grep -q ns_forwarder; then
    echo "Error: ns_forwarder namespace not found"
    echo "Please run: sudo ./setup_ip_isolation.sh first"
    exit 1
fi

# 顯示網路資訊
echo "=== Network Information ==="
echo "Edge Broker IP: 192.168.254.191"
echo "Forwarder IP: $(sudo ip netns exec ns_forwarder ip addr show veth_fwd_ns | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)"
echo "Main Broker: 192.168.254.139:1884"
echo ""

# 測試基本連接
echo "=== Testing Basic Connectivity ==="
echo "1. Testing ping to main broker..."
if sudo ip netns exec ns_forwarder ping -c 2 192.168.254.139; then
    echo "✓ Ping successful"
else
    echo "✗ Ping failed"
    exit 1
fi

echo ""
echo "2. Testing MQTT port connectivity..."
if sudo ip netns exec ns_forwarder timeout 5 nc -z 192.168.254.139 1884; then
    echo "✓ MQTT port reachable"
else
    echo "✗ MQTT port not reachable"
    exit 1
fi

echo ""
echo "=== Testing MQTT Publish ==="
echo "3. Testing MQTT publish from namespace..."

# 從 namespace 發送測試訊息
test_message="{\"test\":\"from_isolated_ip\",\"timestamp\":$(date +%s),\"source\":\"namespace\"}"

if sudo ip netns exec ns_forwarder mosquitto_pub \
    -h 192.168.254.139 \
    -p 1884 \
    -t "test/isolation" \
    -m "$test_message" \
    -d; then
    echo "✓ MQTT publish successful"
else
    echo "✗ MQTT publish failed"
    exit 1
fi

echo ""
echo "=== Monitoring Network Traffic ==="
echo "4. Checking source IP in network traffic..."
echo "   Run this command on main broker to see connections:"
echo "   sudo ss -tupn | grep :1884"
echo "   You should see connections from 192.168.100.2 (not 192.168.254.191)"

echo ""
echo "=== Test Commands ==="
echo "To test manually:"
echo "  # Subscribe on main broker:"
echo "  mosquitto_sub -h 192.168.254.139 -p 1884 -t 'test/#' -v"
echo ""
echo "  # Publish from namespace:"
echo "  sudo ip netns exec ns_forwarder mosquitto_pub -h 192.168.254.139 -p 1884 -t test/manual -m 'hello from isolated IP'"

echo ""
echo "IP isolation test complete! ✓"
