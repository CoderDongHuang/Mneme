package com.mneme;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class MnemeApplication {
    public static void main(String[] args) {
        SpringApplication.run(MnemeApplication.class, args);
    }
}
