cat > /tmp/simple_test.sh << 'EOF'
#!/bin/bash
echo "Simple FIFO test starting..."
HIGH_FIFO="/home/jason/mqtt-edge/forwarder/high_priority_queue.fifo"

while true; do
    echo "Trying to read from HIGH FIFO..."
    if read -r line < "$HIGH_FIFO"; then
        echo "GOT: $line"
        echo "$(date): $line" >> /tmp/fifo_test.log
    else
        echo "Read failed, retrying..."
        sleep 1
    fi
done
EOF
