/*
 * Force-plate data acquisition: NUCLEO-WB55RG reading two FDC2214 chips.
 *
 * Streams CSV over the ST-LINK virtual COM port at 115200 baud:
 *   #  comment / status lines (startup report)
 *   t_ms,ch0,ch1,...,ch7    one line per sample set, raw 28-bit counts
 *
 * Counts are converted to capacitance on the laptop, where the constants are
 * easy to change without reflashing.
 */
#include <stdint.h>
#include "board.h"
#include "fdc2214.h"

/* ------------------------------------------------------------------ clocks */

static uint32_t g_fclk_hz;   /* core / peripheral clock */
static uint32_t g_fref_hz;   /* reference clock fed to the FDC2214 CLKIN pins */

/* Fast enough that sending a sample set costs ~1.3 ms rather than ~5 ms,
 * which is what lets us hit 100 Hz. */
#define BAUD_RATE 460800UL

static void gpio_mode(uint32_t port, uint32_t pin, uint32_t mode, uint32_t pull)
{
    GPIO_MODER(port) = (GPIO_MODER(port) & ~(3UL << (pin * 2))) | (mode << (pin * 2));
    GPIO_PUPDR(port) = (GPIO_PUPDR(port) & ~(3UL << (pin * 2))) | (pull << (pin * 2));
}

static void gpio_af(uint32_t port, uint32_t pin, uint32_t af)
{
    volatile uint32_t *r = (pin < 8) ? &GPIO_AFRL(port) : &GPIO_AFRH(port);
    uint32_t shift = (pin & 7u) * 4u;
    *r = (*r & ~(0xFUL << shift)) | (af << shift);
    GPIO_OSPEEDR(port) = (GPIO_OSPEEDR(port) & ~(3UL << (pin * 2))) | (3UL << (pin * 2));
    gpio_mode(port, pin, MODE_AF, PULL_NONE);
}

/*
 * Prefer the 32 MHz crystal: it is far more stable than the internal RC
 * oscillator, and both FDC chips share it, so any drift is common to all
 * 8 channels and cancels when comparing them. Falls back to the 16 MHz
 * internal oscillator if the crystal does not start.
 */
static void clock_init(void)
{
    FLASH_ACR = (FLASH_ACR & ~7UL) | 1UL;          /* 1 wait state, needed above 18 MHz */

    RCC_CR |= RCC_CR_HSEON;
    uint32_t timeout = 400000;
    while (!(RCC_CR & RCC_CR_HSERDY) && --timeout) {
    }

    if (RCC_CR & RCC_CR_HSERDY) {
        RCC_CFGR = (RCC_CFGR & ~3UL) | 2UL;        /* SYSCLK = HSE */
        while (((RCC_CFGR >> 2) & 3UL) != 2UL) {
        }
        g_fclk_hz = 32000000UL;
    } else {
        RCC_CR |= RCC_CR_HSION;
        while (!(RCC_CR & RCC_CR_HSIRDY)) {
        }
        RCC_CFGR = (RCC_CFGR & ~3UL) | 1UL;        /* SYSCLK = HSI16 */
        while (((RCC_CFGR >> 2) & 3UL) != 1UL) {
        }
        FLASH_ACR &= ~7UL;
        g_fclk_hz = 16000000UL;
    }

    /* MCO = SYSCLK, no division, out on PA8 -> both FDC2214 CLKIN pins. */
    RCC_CFGR = (RCC_CFGR & ~(0xFUL << 24) & ~(7UL << 28)) | (1UL << 24);
    g_fref_hz = g_fclk_hz;

    SYST_RVR = g_fclk_hz / 1000UL - 1UL;
    SYST_CVR = 0;
    SYST_CSR = (1UL << 2) | (1UL << 1) | (1UL << 0);   /* clk=CPU, interrupt, enable */
}

static volatile uint32_t g_ms;

/*
 * Counted by interrupt rather than polled: sending a CSV line blocks for
 * milliseconds at a time, and a polled counter would silently lose ticks
 * while that happens, corrupting every timestamp.
 */
void SysTick_Handler(void)
{
    g_ms++;
}

static uint32_t millis(void)
{
    return g_ms;
}

static void delay_ms(uint32_t ms)
{
    uint32_t start = millis();
    while ((millis() - start) < ms) {
    }
}

/* ------------------------------------------------------------------ serial */

static void uart_init(void)
{
    RCC_APB2ENR |= RCC_APB2ENR_USART1EN;
    gpio_af(GPIOB_BASE, 6, 7);      /* PB6 = USART1_TX */
    gpio_af(GPIOB_BASE, 7, 7);      /* PB7 = USART1_RX */

    USART1_CR1 = 0;
    USART1_BRR = (g_fclk_hz + BAUD_RATE / 2UL) / BAUD_RATE;
    USART1_CR1 = USART_CR1_UE | USART_CR1_TE;
}

static void uart_putc(char c)
{
    while (!(USART1_ISR & USART_ISR_TXE)) {
    }
    USART1_TDR = (uint32_t)(uint8_t)c;
}

static void uart_puts(const char *s)
{
    while (*s)
        uart_putc(*s++);
}

static void uart_putu(uint32_t v)
{
    char buf[11];
    int n = 0;
    if (v == 0) {
        uart_putc('0');
        return;
    }
    while (v) {
        buf[n++] = (char)('0' + (v % 10));
        v /= 10;
    }
    while (n)
        uart_putc(buf[--n]);
}

static void uart_puthex16(uint16_t v)
{
    const char *hex = "0123456789ABCDEF";
    uart_puts("0x");
    for (int i = 12; i >= 0; i -= 4)
        uart_putc(hex[(v >> i) & 0xF]);
}

/* --------------------------------------------------------------------- I2C */

/*
 * TIMINGR fields: [31:28] PRESC, [23:20] SCLDEL, [19:16] SDADEL,
 * [15:8] SCLH, [7:0] SCLL. The board has no pull-up resistors, so we rely on
 * the MCU's internal ones (~40 kohm) and start slow: weak pull-ups make the
 * rising edges sluggish, and a slower clock tolerates that.
 */
static uint32_t timing_for(uint32_t fclk, uint32_t khz)
{
    uint32_t presc = (fclk == 32000000UL) ? 7UL : 3UL;   /* -> 250 ns time base */
    uint32_t half = 2000UL / khz;                        /* half period, in 250 ns steps */
    uint32_t scll = half - 1UL;                          /* 100 kHz -> 20 steps = 5 us */
    uint32_t sclh = (half * 4UL) / 5UL;                  /* high slightly shorter than low */
    if (scll > 0xFF)
        scll = 0xFF;
    if (sclh > 0xFF)
        sclh = 0xFF;
    return (presc << 28) | (4UL << 20) | (2UL << 16) | (sclh << 8) | scll;
}

static void i2c_init(uint32_t timingr)
{
    RCC_APB1ENR1 |= RCC_APB1ENR1_I2C1EN;
    I2C1_CR1 = 0;

    GPIO_OTYPER(GPIOB_BASE) |= (1UL << PIN_SCL) | (1UL << PIN_SDA);  /* open drain */
    gpio_af(GPIOB_BASE, PIN_SCL, 4);
    gpio_af(GPIOB_BASE, PIN_SDA, 4);
    gpio_mode(GPIOB_BASE, PIN_SCL, MODE_AF, PULL_UP);
    gpio_mode(GPIOB_BASE, PIN_SDA, MODE_AF, PULL_UP);

    I2C1_TIMINGR = timingr;
    I2C1_CR1 = I2C_CR1_PE;
}

#define I2C_TIMEOUT 100000u

static int i2c_wait(uint32_t flag)
{
    uint32_t t = I2C_TIMEOUT;
    while (!(I2C1_ISR & flag)) {
        if (I2C1_ISR & I2C_ISR_NACKF)
            return -1;
        if (--t == 0)
            return -2;
    }
    return 0;
}

static void i2c_clear(void)
{
    I2C1_ICR = 0x3F38;      /* clear NACK/STOP/BERR/ARLO etc. */
}

/* Write a 16-bit register: [addr][reg][hi][lo] */
static int fdc_write(uint8_t addr, uint8_t reg, uint16_t val)
{
    i2c_clear();
    I2C1_CR2 = ((uint32_t)addr << 1) | (3UL << 16) | I2C_CR2_AUTOEND | I2C_CR2_START;

    const uint8_t bytes[3] = { reg, (uint8_t)(val >> 8), (uint8_t)val };
    for (int i = 0; i < 3; i++) {
        if (i2c_wait(I2C_ISR_TXIS) != 0)
            return -1;
        I2C1_TXDR = bytes[i];
    }
    if (i2c_wait(I2C_ISR_STOPF) != 0)
        return -1;
    i2c_clear();
    return 0;
}

/* Read a 16-bit register: write the pointer, repeated start, read two bytes. */
static int fdc_read(uint8_t addr, uint8_t reg, uint16_t *out)
{
    i2c_clear();
    I2C1_CR2 = ((uint32_t)addr << 1) | (1UL << 16) | I2C_CR2_START;
    if (i2c_wait(I2C_ISR_TXIS) != 0)
        return -1;
    I2C1_TXDR = reg;
    if (i2c_wait(I2C_ISR_TC) != 0)
        return -1;

    I2C1_CR2 = ((uint32_t)addr << 1) | (2UL << 16) | I2C_CR2_RD_WRN |
               I2C_CR2_AUTOEND | I2C_CR2_START;
    if (i2c_wait(I2C_ISR_RXNE) != 0)
        return -1;
    uint16_t hi = (uint16_t)I2C1_RXDR;
    if (i2c_wait(I2C_ISR_RXNE) != 0)
        return -1;
    uint16_t lo = (uint16_t)I2C1_RXDR;

    if (i2c_wait(I2C_ISR_STOPF) != 0)
        return -1;
    i2c_clear();
    *out = (uint16_t)((hi << 8) | lo);
    return 0;
}

/* ----------------------------------------------------------------- FDC2214 */

static uint8_t g_chip[FDC_CHIPS];      /* detected I2C addresses, 0 = absent */
static int g_chips_found;

static int fdc_present(uint8_t addr)
{
    uint16_t id = 0;
    if (fdc_read(addr, FDC_REG_DEVICE_ID, &id) != 0)
        return 0;
    return id == FDC_DEVICE_ID_2214;
}

static void fdc_configure(uint8_t addr)
{
    /* count = time_us * f_ref / 16e6, kept in 32 bits: MHz first, then scale. */
    uint32_t fref_mhz = g_fref_hz / 1000000UL;
    uint32_t settle = fref_mhz * FDC_SETTLE_US / 16UL;
    uint32_t rcount = fref_mhz * FDC_CONVERT_US / 16UL;
    if (settle < 2)
        settle = 2;
    if (rcount > 0xFFFF)
        rcount = 0xFFFF;

    fdc_write(addr, FDC_REG_CONFIG, FDC_CONFIG_SLEEP);   /* configure while asleep */

    for (int ch = 0; ch < FDC_CHANNELS; ch++) {
        fdc_write(addr, FDC_REG_RCOUNT(ch), (uint16_t)rcount);
        fdc_write(addr, FDC_REG_SETTLECOUNT(ch), (uint16_t)settle);
        fdc_write(addr, FDC_REG_OFFSET(ch), 0x0000);
        fdc_write(addr, FDC_REG_CLOCK_DIVIDERS(ch), FDC_CLOCK_DIVIDERS);
        fdc_write(addr, FDC_REG_DRIVE_CURRENT(ch), FDC_DRIVE_CURRENT);
    }

    fdc_write(addr, FDC_REG_ERROR_CONFIG, 0x0000);
    fdc_write(addr, FDC_REG_MUX_CONFIG, FDC_MUX_CONFIG_4CH);
    fdc_write(addr, FDC_REG_CONFIG, FDC_CONFIG_RUN);     /* wake up and scan */
}

/* One channel's 28-bit result, or 0 if the read failed. */
static uint32_t fdc_sample(uint8_t addr, int ch)
{
    uint16_t msb = 0, lsb = 0;
    if (fdc_read(addr, FDC_REG_DATA_MSB(ch), &msb) != 0)
        return 0;
    if (fdc_read(addr, FDC_REG_DATA_LSB(ch), &lsb) != 0)
        return 0;
    return ((uint32_t)(msb & FDC_DATA_MASK) << 16) | lsb;
}

/* -------------------------------------------------------------------- main */

static void report_chip(uint8_t addr)
{
    uint16_t man = 0, dev = 0, status = 0;
    fdc_read(addr, FDC_REG_MANUFACTURER_ID, &man);
    fdc_read(addr, FDC_REG_DEVICE_ID, &dev);
    fdc_read(addr, FDC_REG_STATUS, &status);

    uart_puts("# chip @ ");
    uart_puthex16(addr);
    uart_puts("  manufacturer=");
    uart_puthex16(man);
    uart_puts(" device=");
    uart_puthex16(dev);
    uart_puts(" status=");
    uart_puthex16(status);
    uart_puts("\r\n");
}

int main(void)
{
    clock_init();

    RCC_AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN | RCC_AHB2ENR_GPIOCEN;
    (void)RCC_AHB2ENR;

    gpio_mode(GPIOB_BASE, PIN_LED, MODE_OUTPUT, PULL_NONE);   /* heartbeat */
    gpio_af(GPIOA_BASE, PIN_MCO, 0);                          /* PA8 = MCO  */

    /* SD low = chip active. Drive both low and give the chips time to boot. */
    gpio_mode(GPIOC_BASE, PIN_SD1, MODE_OUTPUT, PULL_NONE);
    gpio_mode(GPIOC_BASE, PIN_SD2, MODE_OUTPUT, PULL_NONE);
    GPIO_BSRR(GPIOC_BASE) = (1UL << (PIN_SD1 + 16)) | (1UL << (PIN_SD2 + 16));

    uart_init();
    delay_ms(50);

    uart_puts("\r\n# force plate acquisition\r\n# core clock ");
    uart_putu(g_fclk_hz / 1000000UL);
    uart_puts(" MHz, FDC reference ");
    uart_putu(g_fref_hz / 1000000UL);
    uart_puts(" MHz on PA8\r\n");

    /*
     * Find the chips. The bus speed is unknown-good because the PCB has no
     * pull-up resistors, so try progressively slower clocks and keep the first
     * one where a chip answers with the right device ID.
     */
    static const uint32_t khz_options[] = { 400, 100, 50, 20 };
    uint32_t khz_used = 0;

    for (unsigned i = 0; i < sizeof(khz_options) / sizeof(khz_options[0]); i++) {
        i2c_init(timing_for(g_fclk_hz, khz_options[i]));
        delay_ms(10);

        /*
         * Order matters: column order must follow the schematic, not the I2C
         * address. U1 drives Sensor Connector 1 and has ADDR tied high (0x2B),
         * U2 drives Connector 2 with ADDR low (0x2A).
         */
        g_chips_found = 0;
        g_chip[0] = fdc_present(FDC_ADDR_H) ? FDC_ADDR_H : 0;   /* U1, connector 1 */
        g_chip[1] = fdc_present(FDC_ADDR_L) ? FDC_ADDR_L : 0;   /* U2, connector 2 */
        for (int c = 0; c < FDC_CHIPS; c++)
            if (g_chip[c])
                g_chips_found++;

        if (g_chips_found > 0) {
            khz_used = khz_options[i];
            break;
        }
    }

    if (g_chips_found == 0) {
        uart_puts("# ERROR: no FDC2214 responded at 0x2A or 0x2B.\r\n"
                  "# Check 3V3/GND to the PCB and add 4.7k pull-ups on SDA/SCL.\r\n");
    } else {
        uart_puts("# I2C ");
        uart_putu(khz_used);
        uart_puts(" kHz, chips found: ");
        uart_putu((uint32_t)g_chips_found);
        uart_puts("\r\n");
        for (int c = 0; c < FDC_CHIPS; c++)
            if (g_chip[c])
                report_chip(g_chip[c]);
    }

    for (int c = 0; c < FDC_CHIPS; c++)
        if (g_chip[c])
            fdc_configure(g_chip[c]);
    delay_ms(20);

    /* Tell the laptop how to turn counts into capacitance. */
    uart_puts("# fref_hz=");
    uart_putu(g_fref_hz);
    uart_puts(" fin_sel=");
    uart_putu(FDC_FIN_SEL);
    uart_puts(" inductor_nH=18000 cap_pF=33\r\n");
    /* Column identity, stated in the chip/channel terms of the schematic so a
     * reader never has to guess which physical input a column came from. */
    uart_puts("# names=J1-IN0,J1-IN1,J1-IN2,J1-IN3,J2-IN0,J2-IN1,J2-IN2,J2-IN3\r\n");
    uart_puts("t_ms,ch0,ch1,ch2,ch3,ch4,ch5,ch6,ch7\r\n");

    const uint32_t period_ms = 10;      /* 100 samples per second */
    uint32_t next = millis() + period_ms;
    uint32_t beat = millis();

    for (;;) {
        while ((int32_t)(millis() - next) < 0) {
        }
        next += period_ms;
        /* If a slow I2C bus means we cannot keep up, free-run rather than
         * trying to catch up on a backlog that only grows. */
        if ((int32_t)(millis() - next) > (int32_t)period_ms)
            next = millis() + period_ms;

        uart_putu(millis());
        for (int c = 0; c < FDC_CHIPS; c++) {
            for (int ch = 0; ch < FDC_CHANNELS; ch++) {
                uart_putc(',');
                uart_putu(g_chip[c] ? fdc_sample(g_chip[c], ch) : 0);
            }
        }
        uart_puts("\r\n");

        if ((millis() - beat) >= 500) {        /* heartbeat: data is flowing */
            beat = millis();
            GPIO_ODR(GPIOB_BASE) ^= (1UL << PIN_LED);
        }
    }
}
