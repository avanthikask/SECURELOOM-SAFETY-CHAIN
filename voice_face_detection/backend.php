<?php
// Set header for JSON response
header("Content-Type: application/json");

// Retrieve JSON input
$data = json_decode(file_get_contents("php://input"), true);

if (!$data || !isset($data['event'], $data['latitude'], $data['longitude'])) {
    echo json_encode(["status" => "error", "message" => "Invalid input"]);
    exit;
}

// Extract values
$event = $data['event'];
$latitude = $data['latitude'];
$longitude = $data['longitude'];
$timestamp = date('Y-m-d H:i:s');

// Database connection
$conn = new mysqli('localhost', 'root', '', 'safety_system');

if ($conn->connect_error) {
    echo json_encode(["status" => "error", "message" => "Database connection failed"]);
    exit;
}

// Prepare and execute the SQL statement
$stmt = $conn->prepare("INSERT INTO alerts (event, latitude, longitude, timestamp) VALUES (?, ?, ?, ?)");
$stmt->bind_param("sdds", $event, $latitude, $longitude, $timestamp);

if ($stmt->execute()) {
    echo json_encode(["status" => "success", "message" => "Alert stored successfully"]);
} else {
    echo json_encode(["status" => "error", "message" => "Failed to store alert"]);
}

$stmt->close();
$conn->close();
?>
