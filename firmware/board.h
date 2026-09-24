/*
 * NUCLEO-WB55RG + force-plate PCB: pin map and low-level register addresses.
 *
 * Arduino header -> MCU pin (from the board schematic / UM2819):
 *   D14 SDA    -> PB9   (I2C1_SDA, AF4)
 *   D15 SCL    -> PB8   (I2C1_SCL, AF4)
 *   D6  CLKIN  -> PA8   (MCO, AF0)  - reference clock to BOTH FDC2214s
 *   D8  INTB1  -> PC12  (input, unused: we poll instead)
 *   D9  INTB2  -> PA9   (input, unused)
 *   A0  SD1    -> PC0   (output, low = chip 1 running)
 *   A4  SD2    -> PC3   (output, low = chip 2 running)
 *   LD2 green  -> PB0   (heartbeat)
 *   VCP TX/RX  -> PB6/PB7 (USART1, AF7) - appears on the laptop as a COM port
 */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>

#define REG(a) (*(volatile uint32_t *)(a))

/* --- RCC --- */
#define RCC_BASE        0x58000000UL
#define RCC_CR          REG(RCC_BASE + 0x00)
#define RCC_CFGR        REG(RCC_BASE + 0x08)
#define RCC_AHB2ENR     REG(RCC_BASE + 0x4C)
#define RCC_APB1ENR1    REG(RCC_BASE + 0x58)
#define RCC_APB2ENR     REG(RCC_BASE + 0x60)

#define RCC_CR_HSION    (1UL << 8)
#define RCC_CR_HSIRDY   (1UL << 10)
#define RCC_CR_HSEON    (1UL << 16)
#define RCC_CR_HSERDY   (1UL << 17)

#define RCC_AHB2ENR_GPIOAEN (1UL << 0)
#define RCC_AHB2ENR_GPIOBEN (1UL << 1)
#define RCC_AHB2ENR_GPIOCEN (1UL << 2)
#define RCC_APB1ENR1_I2C1EN (1UL << 21)
#define RCC_APB2ENR_USART1EN (1UL << 14)

/* --- FLASH --- */
#define FLASH_ACR       REG(0x58004000UL + 0x00)

/* --- GPIO --- */
#define GPIOA_BASE      0x48000000UL
#define GPIOB_BASE      0x48000400UL
#define GPIOC_BASE      0x48000800UL
#define GPIO_MODER(p)   REG((p) + 0x00)
#define GPIO_OTYPER(p)  REG((p) + 0x04)
#define GPIO_OSPEEDR(p) REG((p) + 0x08)
#define GPIO_PUPDR(p)   REG((p) + 0x0C)
#define GPIO_ODR(p)     REG((p) + 0x14)
#define GPIO_BSRR(p)    REG((p) + 0x18)
#define GPIO_AFRL(p)    REG((p) + 0x20)
#define GPIO_AFRH(p)    REG((p) + 0x24)

#define MODE_INPUT  0u
#define MODE_OUTPUT 1u
#define MODE_AF     2u
#define PULL_NONE   0u
#define PULL_UP     1u

/* --- USART1 (virtual COM port via ST-LINK) --- */
#define USART1_BASE     0x40013800UL
#define USART1_CR1      REG(USART1_BASE + 0x00)
#define USART1_BRR      REG(USART1_BASE + 0x0C)
#define USART1_ISR      REG(USART1_BASE + 0x1C)
#define USART1_TDR      REG(USART1_BASE + 0x28)
#define USART_CR1_UE    (1UL << 0)
#define USART_CR1_TE    (1UL << 3)
#define USART_ISR_TXE   (1UL << 7)
#define USART_ISR_TC    (1UL << 6)

/* --- I2C1 --- */
#define I2C1_BASE       0x40005400UL
#define I2C1_CR1        REG(I2C1_BASE + 0x00)
#define I2C1_CR2        REG(I2C1_BASE + 0x04)
#define I2C1_TIMINGR    REG(I2C1_BASE + 0x10)
#define I2C1_ISR        REG(I2C1_BASE + 0x18)
#define I2C1_ICR        REG(I2C1_BASE + 0x1C)
#define I2C1_RXDR       REG(I2C1_BASE + 0x24)
#define I2C1_TXDR       REG(I2C1_BASE + 0x28)

#define I2C_CR1_PE      (1UL << 0)
#define I2C_CR2_START   (1UL << 13)
#define I2C_CR2_STOP    (1UL << 14)
#define I2C_CR2_RD_WRN  (1UL << 10)
#define I2C_CR2_AUTOEND (1UL << 25)
#define I2C_ISR_TXIS    (1UL << 1)
#define I2C_ISR_RXNE    (1UL << 2)
#define I2C_ISR_NACKF   (1UL << 4)
#define I2C_ISR_STOPF   (1UL << 5)
#define I2C_ISR_TC      (1UL << 6)
#define I2C_ISR_BUSY    (1UL << 15)

/* --- SysTick --- */
#define SYST_CSR        REG(0xE000E010UL)
#define SYST_RVR        REG(0xE000E014UL)
#define SYST_CVR        REG(0xE000E018UL)

/* --- board pins --- */
#define PIN_LED   0u    /* PB0  */
#define PIN_SDA   9u    /* PB9  */
#define PIN_SCL   8u    /* PB8  */
#define PIN_MCO   8u    /* PA8  */
#define PIN_SD1   0u    /* PC0  */
#define PIN_SD2   3u    /* PC3  */

#endif /* BOARD_H */
