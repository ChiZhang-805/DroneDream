use std::{env, fs, process};

use minisign_verify::{PublicKey, Signature};

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: verify-updater-signature <public-key> <signature> <artifact>");
        process::exit(2);
    }

    let public_key_text = fs::read_to_string(&args[1]).expect("read public key");
    let signature_text = fs::read_to_string(&args[2]).expect("read signature");
    let artifact = fs::read(&args[3]).expect("read artifact");
    let public_key = PublicKey::decode(&public_key_text).expect("decode public key");
    let signature = Signature::decode(&signature_text).expect("decode signature");
    public_key
        .verify(&artifact, &signature, false)
        .expect("verify updater signature");

    println!("payload_signature_valid=true");
    println!("trusted_comment_signature_valid=true");
    println!("configured_key_id_matches=true");
    println!("trusted_comment={}", signature.trusted_comment());
}
