use std::time::Duration;
use tokio::time::sleep;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PrinterState {
    Disconnected,
    Connecting,
    Connected,
    Flashing { progress: u8 },
    Error { message: String },
    Recovery,
}

pub struct MoonrakerClient {
    pub endpoint: String,
    pub state: PrinterState,
    pub retry_count: u32,
}

impl MoonrakerClient {
    pub fn new(endpoint: impl Into<String>) -> Self {
        Self {
            endpoint: endpoint.into(),
            state: PrinterState::Disconnected,
            retry_count: 0,
        }
    }

    pub async fn connect(&mut self) -> Result<(), String> {
        self.state = PrinterState::Connecting;
        loop {
            if self.retry_count > 3 {
                self.state = PrinterState::Error {
                    message: "Max connection retries exceeded".to_string(),
                };
                return Err("Connection failed".to_string());
            }
            
            self.state = PrinterState::Connected;
            self.retry_count = 0;
            return Ok(());
        }
    }

    pub async fn flash_firmware(&mut self, _firmware_data: &[u8]) -> Result<(), String> {
        if self.state != PrinterState::Connected {
            return Err("Printer not connected, cannot flash firmware".into());
        }

        self.state = PrinterState::Flashing { progress: 0 };
        
        for progress in (20..=100).step_by(20) {
            sleep(Duration::from_millis(10)).await;
            self.state = PrinterState::Flashing { progress };
        }

        self.state = PrinterState::Connected;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_state_machine_flow() {
        let mut client = MoonrakerClient::new("http://localhost:7125");
        assert_eq!(client.state, PrinterState::Disconnected);

        client.connect().await.unwrap();
        assert_eq!(client.state, PrinterState::Connected);

        client.flash_firmware(b"dummy_firmware").await.unwrap();
        assert_eq!(client.state, PrinterState::Connected);
    }
}
