export function send(url, params) {
  return fetch(url, {
    method: 'post',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: params && JSON.stringify(params)
  }).then(response => {
    if (response.headers.get('Content-Length') == '0') {
      return response.text();
    } else {
      return response.json();
    }
  });
}

export function trancate(value, max = 15, simbol = '…') {
  max = max || 15;
  if (value.length > max) {
    value = value.slice(0, max - 1) + simbol;
  }
  return value;
}
