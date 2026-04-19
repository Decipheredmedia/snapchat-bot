async function renderSnapStatus() {
  const root = document.getElementById('snap-status');
  if (!root) return;

  const response = await fetch('/dashboard/api/stats');
  const stats = await response.json();
  const sent = stats.snap_sent || 0;
  const failed = stats.snap_failed || 0;
  const total = sent + failed;
  const deliveryRate = total === 0 ? 0 : ((sent / total) * 100).toFixed(2);

  root.innerHTML = `
    <h2>Snap Delivery Status</h2>
    <ul>
      <li><strong>Snap queue:</strong> ${total}</li>
      <li><strong>Sent count:</strong> ${sent}</li>
      <li><strong>Failed snaps:</strong> ${failed}</li>
      <li><strong>Delivery rate:</strong> ${deliveryRate}%</li>
    </ul>
  `;
}

setInterval(renderSnapStatus, 3000);
renderSnapStatus();
