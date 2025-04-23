#!/usr/bin/env bash

# Clean up old PulseAudio state (optional, but helps avoid conflicts)
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

# Start PulseAudio in daemon mode
pulseaudio -D --exit-idle-time=-1

# Give PulseAudio time to initialize (optional)
sleep 1

echo "PulseAudio initialized"