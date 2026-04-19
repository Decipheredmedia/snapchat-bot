function healthColor(status) {
  if (status === 'running') return '#22c55e';
  if (status === 'paused') return '#eab308';
  return '#ef4444';
}

async function renderAccountHealth() {
  const root = document.getElementById('account-health');
  if (!root) return;

  const response = await fetch('/dashboard/api/accounts');
  const accounts = await response.json();

  root.innerHTML = '<h2>Account Health</h2>';
  if (!accounts.length) {
    root.innerHTML += '<p>No accounts configured.</p>';
    return;
  }

  const table = document.createElement('table');
  table.innerHTML = `
    <thead>
      <tr>
        <th>Account</th><th>Session</th><th>Proxy</th><th>Last Active</th><th>Add Count</th><th>Error Count</th>
      </tr>
    </thead>
    <tbody>
      ${accounts.map(account => `
        <tr>
          <td>${account.username}</td>
          <td><span style="color:${healthColor(account.session_status)};font-weight:600;">${account.session_status}</span></td>
          <td>${account.assigned_proxy ? 'healthy' : 'missing'}</td>
          <td>${account.last_active || '-'}</td>
          <td>${account.add_count ?? 0}</td>
          <td>${account.error_count ?? 0}</td>
        </tr>
      `).join('')}
    </tbody>
  `;

  root.appendChild(table);
}

setInterval(renderAccountHealth, 5000);
renderAccountHealth();
