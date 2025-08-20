CC = gcc
CFLAGS = -Wall -fPIC -O2 $(shell pkg-config --cflags libmosquitto libcurl json-c)
LDFLAGS = -shared $(shell pkg-config --libs libmosquitto libcurl json-c) -lpthread
TARGET = simple_edge_plugin.so
SOURCE = time_delta_edge_plugin_fifo.c

.PHONY: all install clean test

all: $(TARGET)

$(TARGET): $(SOURCE) uthash.h
	$(CC) $(CFLAGS) $(SOURCE) -o $(TARGET) $(LDFLAGS)
	@echo "✓ Plugin compiled successfully"

install: $(TARGET)
	sudo mkdir -p /usr/lib/mosquitto/plugins
	sudo cp $(TARGET) /usr/lib/mosquitto/plugins/
	@echo "✓ Plugin installed"

clean:
	rm -f $(TARGET)

test:
	$(CC) $(CFLAGS) -fsyntax-only $(SOURCE)
	@echo "✓ Syntax check passed"
