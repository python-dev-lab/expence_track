document.addEventListener('DOMContentLoaded', () => {
    const { pieLabels, pieValues, monthlyLabels, monthlyValues } = window.chartData || {};
    const palette = ['#4e73df','#1cc88a','#36b9cc','#f6c23e','#e74a3b',
                     '#858796','#5a5c69','#20c997','#fd7e14','#6f42c1'];

    const pieEl = document.getElementById('pieChart');
    if (pieEl && pieLabels && pieLabels.length) {
        new Chart(pieEl, {
            type: 'doughnut',
            data: { labels: pieLabels, datasets: [{
                data: pieValues, backgroundColor: palette,
                borderWidth: 2, borderColor: '#fff'
            }]},
            options: {
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: { callbacks: {
                        label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(2)} ₽`
                    }}
                },
                cutout: '55%'
            }
        });
    } else if (pieEl) {
        pieEl.parentElement.innerHTML = '<p class="text-center text-muted py-5">Нет данных</p>';
    }

    const barEl = document.getElementById('barChart');
    if (barEl && monthlyLabels && monthlyLabels.length) {
        new Chart(barEl, {
            type: 'bar',
            data: { labels: monthlyLabels, datasets: [{
                label: 'Расходы, ₽', data: monthlyValues,
                backgroundColor: '#4e73df', borderRadius: 8
            }]},
            options: {
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { callback: v => v + ' ₽' } } }
            }
        });
    } else if (barEl) {
        barEl.parentElement.innerHTML = '<p class="text-center text-muted py-5">Нет данных</p>';
    }
});
