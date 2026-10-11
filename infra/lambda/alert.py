import os
import urllib.parse
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
 
import boto3
 
s3 = boto3.client("s3")
ses = boto3.client("ses")
ADDRESS = os.environ["ALERT_EMAIL"]  # same address is sender and recipient
 
 
def handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        when = record.get("eventTime", "")
        image = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
 
        msg = MIMEMultipart("related")
        msg["Subject"] = f"Motion detected {when}"
        msg["From"] = ADDRESS
        msg["To"] = ADDRESS
        html = (
            f"<p>Motion detected at {when} (UTC).</p>"
            '<img src="cid:snapshot" style="max-width:100%">'
            f"<p>s3://{bucket}/{key}</p>"
        )
        msg.attach(MIMEText(html, "html"))
 
        img = MIMEImage(image, _subtype="jpeg")
        img.add_header("Content-ID", "<snapshot>")
        img.add_header("Content-Disposition", "inline",
                       filename=os.path.basename(key))
        msg.attach(img)
 
        ses.send_raw_email(
            Source=ADDRESS,
            Destinations=[ADDRESS],
            RawMessage={"Data": msg.as_string()},
        )
 