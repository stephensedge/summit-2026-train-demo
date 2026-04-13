// --- Pin Definitions ---
// L298N Pins
const int enA = 9;  // PWM output to motor (Speed)
const int in1 = 8;  // Direction pin 1
const int in2 = 7;  // Direction pin 2

// Analog Input Pins from IONA (via Voltage Dividers)
const int speedPin = A0; // Connected to AO0 (0-10.0V)
const int dirPin = A1;   // Connected to AO1 (0V or 10.0V)

// --- Variables ---
unsigned long lastSerialPrint = 0;

void setup() {
  Serial.begin(9600);
  Serial.println("Arduino Motor Controller Online!");
  Serial.println("Awaiting signals from IONA...");

  pinMode(enA, OUTPUT);
  pinMode(in1, OUTPUT);
  pinMode(in2, OUTPUT);
  
  // Ensure motor is OFF and safely locked at startup
  analogWrite(enA, 0);
  digitalWrite(in1, LOW);
  digitalWrite(in2, LOW);
}

void loop() {
  // 1. Read Inputs
  int speedRaw = analogRead(speedPin); 
  int dirRaw = analogRead(dirPin);     

  // 2. Process Speed
  int pwmOut = 0;
  if (speedRaw > 15) { 
    pwmOut = map(speedRaw, 0, 1023, 0, 255);
    pwmOut = constrain(pwmOut, 0, 255);
  }

  // 3. Process Direction
  // 512 (~2.5V) is the logical midpoint to switch states
  bool isForward = (dirRaw < 512);

  // 4. Update L298N Hardware
  if (isForward) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
  } else {
    digitalWrite(in1, LOW);
    digitalWrite(in2, HIGH);
  }
  
  analogWrite(enA, pwmOut);

  // 5. Print Diagnostics to Serial Monitor (Updates every 500ms)
  if (millis() - lastSerialPrint > 500) {
    // 1023 max raw = exactly 10.0V max output based on new Python limits
    float estSpeedVolts = (speedRaw / 1023.0) * 10.0;
    
    // Clean up minor floating-point jitter for display
    if (estSpeedVolts > 9.9) estSpeedVolts = 10.0; 
    
    int percent = map(pwmOut, 0, 255, 0, 100);

    Serial.print("IONA Speed Signal: ~");
    Serial.print(estSpeedVolts, 1);
    Serial.print("V | ");
    
    Serial.print("Motor PWM: ");
    Serial.print(pwmOut);
    Serial.print(" (");
    Serial.print(percent);
    Serial.print("%) | ");

    if (pwmOut == 0) {
      Serial.println("State: STOPPED");
    } else {
      Serial.print("State: RUNNING ");
      Serial.println(isForward ? "FORWARD" : "REVERSE");
    }
    
    lastSerialPrint = millis();
  }
}