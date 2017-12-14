export function call(method, url, data) {
  let params = {
    method: method,
    credentials: 'same-origin'
  };
  if (method == 'post') {
    (params.headers = { 'Content-Type': 'application/json' }),
      (params.body = data && JSON.stringify(data));
  }
  return fetch(url, params).then(response => {
    if (!response.ok) {
      throw new Error(response);
    }
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
