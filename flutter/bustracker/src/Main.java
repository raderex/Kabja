//TIP To <b>Run</b> code, press <shortcut actionId="Run"/> or
// click the <icon src="AllIcons.Actions.Execute"/> icon in the gutter.
import javax.swing.*;
import java.awt.*;

//TIP To <b>Run</b> code, press <shortcut actionId="Run"/> or
// click the <icon src="AllIcons.Actions.Execute"/> icon in the gutter.
public class Main {
    public static void main(String[] args) {
        // Create the main window (JFrame)
        JFrame frame = new JFrame("Bus Tracker");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setSize(400, 300);

        // Create a container panel
        JPanel panel = new JPanel();
        panel.setLayout(new BorderLayout());
        panel.setBorder(BorderFactory.createEmptyBorder(20, 20, 20, 20));

        // Add a welcome message
        JLabel label = new JLabel("Bus Tracker System", SwingConstants.CENTER);
        label.setFont(new Font("Serif", Font.BOLD, 24));
        panel.add(label, BorderLayout.NORTH);

        // Add a status message in the center
        JLabel statusLabel = new JLabel("Status: Ready", SwingConstants.CENTER);
        panel.add(statusLabel, BorderLayout.CENTER);

        // Add a button at the bottom
        JButton button = new JButton("View Active Buses");
        button.addActionListener(e -> {
            statusLabel.setText("Fetching bus data...");
            JOptionPane.showMessageDialog(frame, "Feature coming soon!");
        });
        panel.add(button, BorderLayout.SOUTH);

        // Add the panel to the frame
        frame.add(panel);

        // Center the window and make it visible
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);

        System.out.println("The UI has been launched!");
    }
}
