#!/usr/bin/env python3

import argparse
import sys
import paho.mqtt.publish as publish

def main():
    parser = argparse.ArgumentParser(description="Send commands to the MQTT motor controller.")
    
    # Strictly enforce the allowed relative commands
    parser.add_argument(
        "command", 
        choices=["start", "stop", "faster", "slower", "forward", "reverse"], 
        help="The command to send to the motor."
    )
    
    # Optional arguments to override defaults
    parser.add_argument("-b", "--broker", default="localhost", help="MQTT broker address (default: localhost)")
    parser.add_argument("-p", "--port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("-t", "--topic", default="motor/control", help="MQTT topic (default: motor/control)")

    args = parser.parse_args()

    print(f"Sending '{args.command}' to topic '{args.topic}' at {args.broker}:{args.port}...")

    try:
        publish.single(
            topic=args.topic,
            payload=args.command,
            hostname=args.broker,
            port=args.port
        )
        print("Success!")
    except Exception as e:
        print(f"Error sending message: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()